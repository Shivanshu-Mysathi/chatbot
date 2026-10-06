from __future__ import annotations

import logging
import httpx
from app.core.config import get_settings
from app.services.ollama_service import ModelUnavailable, OllamaError, OllamaTimeout

logger = logging.getLogger(__name__)

class EmbeddingDimensionMismatch(OllamaError):
    code = 'EMBEDDING_DIMENSION_MISMATCH'
    public_message = 'The local knowledge service is temporarily unavailable.'

async def embed_texts(texts: list[str], *, batch_size: int | None = None) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    batch_size = batch_size or settings.rag_embedding_batch_size
    vectors: list[list[float]] = []
    timeout = httpx.Timeout(settings.ollama_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            try:
                response = await client.post(
                    f"{settings.ollama_base_url.rstrip('/')}/api/embed",
                    json={'model':settings.embedding_model, 'input':batch},
                )
                if response.status_code == 404:
                    raise ModelUnavailable('Configured local embedding model is unavailable.')
                response.raise_for_status()
                embeddings = response.json()['embeddings']
                if len(embeddings) != len(batch):
                    raise EmbeddingDimensionMismatch('Ollama returned a different number of embeddings than inputs.')
                for vector in embeddings:
                    if len(vector) != settings.embedding_dimensions:
                        raise EmbeddingDimensionMismatch(
                            f'Embedding model returned {len(vector)} dimensions; the database schema is configured for {settings.embedding_dimensions}.'
                        )
                vectors.extend(embeddings)
            except (ModelUnavailable, EmbeddingDimensionMismatch):
                raise
            except httpx.TimeoutException as exc:
                raise OllamaTimeout() from exc
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise OllamaError() from exc
    return vectors

async def check_embedding_model() -> int:
    vector = await embed_texts(['Local embedding model dimension check.'], batch_size=1)
    dimensions = len(vector[0])
    logger.info('Local embedding model verified model=%s dimensions=%d', get_settings().embedding_model, dimensions)
    return dimensions
