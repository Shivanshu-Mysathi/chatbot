from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import require_api_key
from app.db.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import send_message
from app.services.ollama_service import OllamaError
from app.auth.user_identity import AuthenticatedUser, get_authenticated_user

router = APIRouter()
@router.post('/chat', response_model=ChatResponse, dependencies=[Depends(require_api_key)])
async def chat(body: ChatRequest, db: AsyncSession = Depends(get_db), identity: AuthenticatedUser | None = Depends(get_authenticated_user)):
    try:
        sid, mid, answer, elapsed = await send_message(db, body.message, body.session_id, identity=identity)
        from app.core.config import get_settings
        return ChatResponse(session_id=sid, message_id=mid, response=answer, model=get_settings().ollama_model, response_time_ms=elapsed)
    except LookupError:
        raise HTTPException(404, detail={'code':'SESSION_NOT_FOUND','message':'Conversation session was not found.'})
    except OllamaError as exc:
        await db.rollback()
        raise HTTPException(503, detail={'code':exc.code,'message':exc.public_message})
