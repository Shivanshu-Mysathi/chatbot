from __future__ import annotations
import argparse
import asyncio
import logging
import re
from app.db.database import SessionLocal
from app.rag.ingestion import ingest_document

def main() -> None:
    parser = argparse.ArgumentParser(description='Ingest a DOCX into the local MySathi knowledge base.')
    parser.add_argument('--file', required=True, help='Path to a DOCX file (absolute paths are supported).')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    try:
        result = asyncio.run(run(args.file))
    except Exception as exc:
        message = re.sub(r'(?i)(://[^:/@\s]+:)[^@\s]+@', r'\1***@', str(exc))
        logger.error('Knowledge ingestion failed error_type=%s detail=%s', type(exc).__name__, message)
        print('Errors: 1')
        raise SystemExit(1) from None
    print(f"Document: {result['filename']}")
    print(f"Title: {result['title']}")
    print(f"Pages: {result['total_pages'] if result['total_pages'] else 'not available in DOCX pagination metadata'}")
    print(f"Chunks created: {result['chunks_created']}")
    print(f"Embeddings created: {result['embeddings_created']}")
    print(f"Skipped duplicates: {result['skipped_duplicates']}")
    print(f"Errors: {result['errors']}")

async def run(path: str) -> dict:
    async with SessionLocal() as db:
        return await ingest_document(db, path)

if __name__ == '__main__':
    main()
