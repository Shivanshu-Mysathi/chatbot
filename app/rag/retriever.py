from __future__ import annotations
import logging
import time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.rag.context import RAGResult
from app.rag.embeddings import embed_texts

logger = logging.getLogger(__name__)

async def retrieve(db: AsyncSession, query: str, *, top_k: int | None = None) -> list[RAGResult]:
    started = time.perf_counter()
    settings = get_settings()
    limit = min(max(1, top_k or settings.rag_top_k), 20)
    vector = (await embed_texts([query], batch_size=1))[0]
    distance = KnowledgeChunk.embedding.cosine_distance(vector)
    similarity = (1.0 - distance).label('similarity')
    statement = (select(KnowledgeChunk, KnowledgeDocument, similarity)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .where(KnowledgeDocument.is_active.is_(True), similarity >= settings.rag_similarity_threshold)
        .order_by(distance)
        .limit(limit))
    rows = (await db.execute(statement)).all()
    results = [RAGResult(
        content=chunk.content, document_id=document.id, filename=document.filename, chunk_id=getattr(chunk, 'id', None),
        page_number=chunk.page_number, section_title=chunk.section_title,
        subsection_title=chunk.subsection_title, similarity=float(score),
    ) for chunk, document, score in rows]
    elapsed = int((time.perf_counter() - started) * 1000)
    logger.info('RAG retrieval complete query_chars=%d top_k=%d results=%d latency_ms=%d', len(query), limit, len(results), elapsed)
    return results
