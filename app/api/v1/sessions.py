import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import require_api_key
from app.db.database import get_db
from app.schemas.session import SessionOut
from app.schemas.chat import MessageOut
from app.services import session_service as svc
router = APIRouter(dependencies=[Depends(require_api_key)])
@router.get('', response_model=list[SessionOut])
async def list_sessions(limit: int = Query(50, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    return await svc.list_sessions(db, limit)
@router.get('/{session_id}', response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    item = await svc.get_session(db, session_id)
    if not item: raise HTTPException(404, detail={'code':'SESSION_NOT_FOUND','message':'Conversation session was not found.'})
    return item
@router.get('/{session_id}/messages', response_model=list[MessageOut])
async def get_messages(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if not await svc.get_session(db, session_id): raise HTTPException(404, detail={'code':'SESSION_NOT_FOUND','message':'Conversation session was not found.'})
    return await svc.get_messages(db, session_id)
@router.delete('/{session_id}', status_code=204)
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    if not await svc.delete_session(db, session_id): raise HTTPException(404, detail={'code':'SESSION_NOT_FOUND','message':'Conversation session was not found.'})
