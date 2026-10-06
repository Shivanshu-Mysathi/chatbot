import logging, time, uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession
from app.services.ollama_service import OllamaService
from app.rag.context import build_user_prompt
from app.rag.service import RAGService
from app.auth.user_identity import AuthenticatedUser

logger = logging.getLogger(__name__)

async def send_message(db: AsyncSession, message: str, session_id: uuid.UUID | None, identity: AuthenticatedUser | None = None):
    if session_id:
        session = await db.get(ChatSession, session_id)
        if not session or not session.is_active: raise LookupError('SESSION_NOT_FOUND')
        if identity and session.user_id and session.user_id != identity.user_id: raise LookupError('SESSION_NOT_FOUND')
    else:
        session = ChatSession(title=message[:80], user_id=identity.user_id if identity else None,
            user_email=identity.email if identity else None, user_name=identity.name if identity else None); db.add(session); await db.flush()
    if identity and session.user_id == identity.user_id:
        session.user_email = identity.email or session.user_email
        session.user_name = identity.name or session.user_name
    elif identity and session.user_id is None:
        # A validated identity may claim an unowned legacy session; arbitrary request fields never reach here.
        session.user_id = identity.user_id
        session.user_email = identity.email
        session.user_name = identity.name
    session.updated_at = datetime.now(timezone.utc)
    user_message = ChatMessage(session_id=session.id, role='user', content=message)
    db.add(user_message)
    await db.commit()  # Preserve the user query even if local inference fails.
    history = (await db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(get_settings().max_context_messages))).all()
    settings = get_settings()
    if settings.rag_enabled:
        retrieved = await RAGService().retrieve(db, message)
        user_message.rag_used = bool(retrieved)
        user_message.retrieved_chunks = [{"chunk_id": str(item.chunk_id) if getattr(item, "chunk_id", None) else None,
            "section_title": item.section_title, "subsection_title": item.subsection_title, "similarity": item.similarity}
            for item in retrieved]
        await db.commit()
        system_prompt = settings.rag_system_prompt
        current_content = build_user_prompt(message, retrieved)
    else:
        user_message.rag_used = False
        user_message.retrieved_chunks = []
        await db.commit()
        system_prompt = settings.system_prompt
        current_content = message
    previous_messages = [m for m in reversed(history) if m.id != user_message.id]
    messages = [{'role':'system','content':system_prompt}]
    messages.extend({'role':m.role,'content':m.content} for m in previous_messages)
    messages.append({'role':'user','content':current_content})
    start = time.perf_counter()
    answer = await OllamaService().chat(messages)
    elapsed = int((time.perf_counter()-start)*1000)
    logger.info('Ollama generation complete model=%s latency_ms=%d', settings.ollama_model, elapsed)
    result = ChatMessage(session_id=session.id, role='assistant', content=answer, model=settings.ollama_model, response_time_ms=elapsed)
    db.add(result); await db.commit(); await db.refresh(result)
    return session.id, result.id, answer, elapsed
