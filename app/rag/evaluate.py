from __future__ import annotations
import asyncio
import json
from pathlib import Path
from app.db.database import SessionLocal
from app.rag.retriever import retrieve

DATASET = Path(__file__).resolve().parents[2] / 'tests' / 'data' / 'rag_evaluation.json'

async def evaluate() -> tuple[int, int, list[str]]:
    cases = json.loads(DATASET.read_text(encoding='utf-8'))['cases']
    misses=[]
    async with SessionLocal() as db:
        for case in cases:
            results=await retrieve(db, case['question'])
            excerpts='\n'.join(result.content.lower() for result in results)
            if not any(evidence.lower() in excerpts for evidence in case['expected_source_evidence']):
                misses.append(case['question'])
    return len(cases)-len(misses), len(cases), misses

def main() -> None:
    hit, total, misses=asyncio.run(evaluate())
    print(f'Manual evidence recall: {hit}/{total}')
    for question in misses:
        print(f'MISS: {question}')
    if misses:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
