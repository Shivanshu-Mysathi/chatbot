import httpx, pytest
from unittest.mock import AsyncMock, patch
from app.services.ollama_service import OllamaService, OllamaTimeout

@pytest.mark.asyncio
async def test_ollama_timeout():
    with patch('httpx.AsyncClient.post', new=AsyncMock(side_effect=httpx.TimeoutException('timeout'))):
        with pytest.raises(OllamaTimeout): await OllamaService().chat([])
