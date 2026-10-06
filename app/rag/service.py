from app.rag.retriever import retrieve

class RAGService:
    async def retrieve(self, db, query: str, *, top_k: int | None = None):
        return await retrieve(db, query, top_k=top_k)
