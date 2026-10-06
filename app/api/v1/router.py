from fastapi import APIRouter
from app.api.v1 import chat, sessions
from app.api.v1.admin.router import router as admin_router
router = APIRouter()
router.include_router(chat.router, tags=['chat'])
router.include_router(sessions.router, prefix='/sessions', tags=['sessions'])
router.include_router(admin_router, prefix='/admin')
