import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import ChatMessage, ChatSession

async def list_sessions(db: AsyncSession, limit: int = 50):
    return (await db.scalars(select(ChatSession).where(ChatSession.is_active.is_(True)).order_by(ChatSession.updated_at.desc()).limit(limit))).all()
async def get_session(db: AsyncSession, session_id: uuid.UUID):
    item = await db.get(ChatSession, session_id)
    return item if item and item.is_active else None
async def get_messages(db: AsyncSession, session_id: uuid.UUID):
    return (await db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.id))).all()
async def delete_session(db: AsyncSession, session_id: uuid.UUID):
    item = await get_session(db, session_id)
    if not item: return False
    item.is_active = False
    await db.commit()
    return True
