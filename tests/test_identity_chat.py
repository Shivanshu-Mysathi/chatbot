import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.auth.user_identity import AuthenticatedUser
from app.db.models import ChatMessage, ChatSession
from app.services import chat_service


def test_verified_identity_is_persisted_on_new_chat_session(monkeypatch):
    class FakeDB:
        def __init__(self): self.objects=[]
        async def get(self, *args): return None
        def add(self, value): self.objects.append(value)
        async def flush(self):
            for item in self.objects:
                if isinstance(item, ChatSession) and item.id is None: item.id=uuid.uuid4()
        async def commit(self): pass
        async def scalars(self, statement): return SimpleNamespace(all=lambda:[])
        async def refresh(self, value): pass

    identity=AuthenticatedUser("aws-user-17","person@example.test","Example Person")
    fake_settings=SimpleNamespace(rag_enabled=False,system_prompt="test",max_context_messages=10,ollama_model="qwen3:14b")
    monkeypatch.setattr(chat_service,"get_settings",lambda:fake_settings)
    db=FakeDB()
    with patch.object(chat_service.OllamaService,"chat",new=AsyncMock(return_value="Answer")):
        sid,mid,answer,elapsed=asyncio.run(chat_service.send_message(db,"A question",None,identity=identity))
    session=next(x for x in db.objects if isinstance(x,ChatSession))
    user_message=next(x for x in db.objects if isinstance(x,ChatMessage) and x.role=="user")
    assert session.id==sid
    assert (session.user_id,session.user_email,session.user_name)==("aws-user-17","person@example.test","Example Person")
    assert user_message.rag_used is False
    assert answer=="Answer"
