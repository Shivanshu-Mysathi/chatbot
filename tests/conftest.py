import os
os.environ.setdefault('CHAT_API_KEY','test-secret')
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://postgres:postgres@localhost:5432/test_db')
import asyncio
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

class LocalASGITestClient:
    """Synchronous test facade over HTTPX ASGITransport, without lifespan startup."""
    def __init__(self, application):
        self.app = application

    def request(self, method, url, **kwargs):
        async def send():
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url='http://testserver') as client:
                return await client.request(method, url, **kwargs)
        return asyncio.run(send())

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request('DELETE', url, **kwargs)

@pytest.fixture
def client():
    yield LocalASGITestClient(app)
