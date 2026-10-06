from __future__ import annotations
import argparse
import asyncio
import logging
from app.db.database import SessionLocal
from app.rag.retriever import retrieve

async def run(query: str, top_k: int | None = None):
    async with SessionLocal() as db:
        return await retrieve(db, query, top_k=top_k)

def main() -> None:
    parser = argparse.ArgumentParser(description='Search the local MySathi knowledge base.')
    parser.add_argument('query', help='Question or phrase to retrieve from the ingested manual.')
    parser.add_argument('--top-k', type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    results = asyncio.run(run(args.query, args.top_k))
    print(f'Query: {args.query}\n\nTop results:')
    if not results:
        print('No relevant chunks found above the configured similarity threshold.')
    for index, result in enumerate(results, 1):
        print(f'\n{index}.\nSection: {result.section_title or "—"}\nSubsection: {result.subsection_title or "—"}')
        print(f'Page: {result.page_number or "unavailable"}\nSimilarity: {result.similarity:.4f}\nContent: {result.content}')

if __name__ == '__main__':
    main()
