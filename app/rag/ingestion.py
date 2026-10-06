from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.rag.chunker import chunk_document
from app.rag.embeddings import embed_texts
from app.rag.parser import parse_docx

logger = logging.getLogger(__name__)

def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

async def ingest_document(db: AsyncSession, path: str | Path, *, embedder=None) -> dict:
    source = Path(path).expanduser().resolve()
    logger.info('Knowledge ingestion started filename=%s', source.name)
    parsed = parse_docx(source)
    file_hash = sha256_file(source)
    duplicate = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.file_hash == file_hash))
    if duplicate:
        logger.info('Knowledge document already ingested filename=%s document_id=%s', source.name, duplicate.id)
        return {'filename':source.name, 'title':parsed.title, 'total_pages':duplicate.total_pages,
                'chunks_created':0, 'embeddings_created':0, 'skipped_duplicates':1, 'errors':0,
                'document_id':str(duplicate.id)}
    # The duplicate check starts an implicit SQLAlchemy transaction; finish it
    # before opening the all-or-nothing document/version insert transaction.
    await db.rollback()

    settings = get_settings()
    chunks = chunk_document(parsed.blocks, size=settings.rag_chunk_size, overlap=settings.rag_chunk_overlap)
    logger.info('Knowledge document parsed filename=%s pages=%s blocks=%d chunks=%d', source.name,
                parsed.total_pages if parsed.total_pages else 'unavailable', len(parsed.blocks), len(chunks))
    if not chunks:
        raise ValueError('No searchable content was produced from the DOCX.')
    vectors = await (embedder or embed_texts)([chunk.content for chunk in chunks], batch_size=settings.rag_embedding_batch_size)
    if len(vectors) != len(chunks):
        raise ValueError('Embedding service returned a mismatched vector count.')
    logger.info('Knowledge embeddings generated filename=%s count=%d dimension=%d', source.name, len(vectors), settings.embedding_dimensions)

    document = KnowledgeDocument(
        filename=source.name, title=parsed.title, file_hash=file_hash, source_type='docx',
        total_pages=parsed.total_pages, total_chunks=len(chunks), metadata_json=parsed.metadata,
    )
    try:
        async with db.begin():
            previous = (await db.scalars(select(KnowledgeDocument).where(
                KnowledgeDocument.filename == source.name, KnowledgeDocument.is_active.is_(True)
            ))).all()
            for version in previous:
                version.is_active = False
            db.add(document)
            await db.flush()
            db.add_all([KnowledgeChunk(
                document_id=document.id, chunk_index=chunk.chunk_index, content=chunk.content,
                embedding=vector, page_number=chunk.page_number, section_title=chunk.section_title,
                subsection_title=chunk.subsection_title, language=chunk.language,
                metadata_json=chunk.metadata,
            ) for chunk, vector in zip(chunks, vectors, strict=True)])
    except IntegrityError:
        await db.rollback()
        duplicate = await db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.file_hash == file_hash))
        if duplicate:
            return {'filename':source.name, 'title':parsed.title, 'total_pages':duplicate.total_pages,
                    'chunks_created':0, 'embeddings_created':0, 'skipped_duplicates':1, 'errors':0,
                    'document_id':str(duplicate.id)}
        raise
    logger.info('Knowledge database insert completed filename=%s chunks=%d', source.name, len(chunks))
    return {'filename':source.name, 'title':parsed.title, 'total_pages':parsed.total_pages,
            'chunks_created':len(chunks), 'embeddings_created':len(vectors), 'skipped_duplicates':0,
            'errors':0, 'document_id':str(document.id)}
