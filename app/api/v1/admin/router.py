from fastapi import APIRouter
from app.api.v1.admin import data
from app.api.v1.admin.security import auth_router, protected_auth_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(protected_auth_router)
router.include_router(data.router)
