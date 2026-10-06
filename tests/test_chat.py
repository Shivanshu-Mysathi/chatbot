import asyncio
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.core.security import require_api_key
from app.main import app

def test_auth_missing():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_api_key(None))
    assert exc.value.status_code == 401
    assert exc.value.detail['code'] == 'MISSING_API_KEY'

def test_auth_invalid_bearer_token():
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials='wrong')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_api_key(credentials))
    assert exc.value.status_code == 401
    assert exc.value.detail['code'] == 'INVALID_API_KEY'

def test_auth_valid_bearer_token():
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials='test-secret')
    assert asyncio.run(require_api_key(credentials)) is None

def test_openapi_declares_http_bearer_security():
    schema = app.openapi()
    security_scheme = schema['components']['securitySchemes']['HTTPBearer']
    assert security_scheme == {'type':'http','scheme':'bearer'}
    chat_operation = schema['paths']['/api/v1/chat']['post']
    assert {'HTTPBearer': []} in chat_operation['security']
    assert not any(p.get('name', '').lower() == 'authorization' for p in chat_operation.get('parameters', []))

def test_empty_message(client):
    response = client.post('/api/v1/chat', headers={'Authorization':'Bearer test-secret'}, json={'message':'  '})
    assert response.status_code == 422

def test_valid_chat_mocked(client):
    from unittest.mock import AsyncMock, patch
    from app.db.database import get_db
    class FakeDB:
        async def get(self, *a): return None
        def add(self, *a): pass
        async def flush(self): pass
        async def scalars(self, *a):
            class R:
                def all(self): return []
            return R()
        async def commit(self): pass
        async def refresh(self, result): result.id='11111111-1111-1111-1111-111111111111'
    # Exercise the authenticated route/service boundary without PostgreSQL or a real model.
    async def override_db(): yield FakeDB()
    client.app.dependency_overrides[get_db] = override_db
    from app.api.v1 import chat as chat_route
    async def fake_send(db, message, sid, identity=None):
        import uuid
        return uuid.uuid4(), uuid.uuid4(), 'Hello!', 5
    with patch.object(chat_route, 'send_message', new=AsyncMock(side_effect=fake_send)):
        response = client.post('/api/v1/chat', headers={'Authorization':'Bearer test-secret'}, json={'message':'hi'})
    client.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()['response'] == 'Hello!'
