from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

def test_health(client):
    assert client.get('/health').json() == {'status':'ok'}

def test_health_ollama(client):
    with patch('app.services.ollama_service.OllamaService.check', new=AsyncMock(return_value=True)):
        assert client.get('/health/ollama').json()['ollama'] == 'reachable'

def test_health_ollama_failure(client):
    from app.services.ollama_service import OllamaError
    with patch('app.services.ollama_service.OllamaService.check', new=AsyncMock(side_effect=OllamaError())):
        assert client.get('/health/ollama').status_code == 503
