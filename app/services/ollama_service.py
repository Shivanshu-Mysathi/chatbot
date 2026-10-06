import httpx
from app.core.config import get_settings

class OllamaError(Exception):
    code = 'OLLAMA_UNAVAILABLE'
    public_message = 'AI service is temporarily unavailable.'
class OllamaTimeout(OllamaError):
    code = 'OLLAMA_TIMEOUT'
class ModelUnavailable(OllamaError):
    code = 'MODEL_UNAVAILABLE'

class OllamaService:
    def __init__(self): self.settings = get_settings()
    async def check(self) -> bool:
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                response = await client.get(f"{self.settings.ollama_base_url.rstrip('/')}/api/tags")
                response.raise_for_status()
                names = {m.get('name') for m in response.json().get('models', [])}
                if self.settings.ollama_model not in names: raise ModelUnavailable('Configured model is not installed.')
                return True
            except ModelUnavailable: raise
            except (httpx.HTTPError, ValueError) as exc: raise OllamaError() from exc
    async def chat(self, messages: list[dict[str,str]]) -> str:
        async with httpx.AsyncClient(timeout=self.settings.ollama_timeout) as client:
            try:
                response = await client.post(f"{self.settings.ollama_base_url.rstrip('/')}/api/chat", json={'model':self.settings.ollama_model,'messages':messages,'stream':False})
                if response.status_code == 404: raise ModelUnavailable('Configured model is not installed.')
                response.raise_for_status()
                return response.json()['message']['content']
            except ModelUnavailable: raise
            except httpx.TimeoutException as exc: raise OllamaTimeout() from exc
            except (httpx.HTTPError, ValueError, KeyError) as exc: raise OllamaError() from exc
