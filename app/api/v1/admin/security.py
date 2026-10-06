from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.security import APIKeyCookie
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import AdminSession
from app.schemas.admin import AdminLogin, AdminMe

password_hasher = PasswordHasher()
auth_router = APIRouter(prefix="/auth", tags=["admin authentication"])
admin_cookie_scheme = APIKeyCookie(name="admin_session", scheme_name="AdminSessionCookie", auto_error=False)


def _token_hash(token: str) -> str:
    secret = get_settings().admin_session_secret
    if not secret or len(secret) < 32:
        raise HTTPException(503, detail={"code": "ADMIN_AUTH_NOT_CONFIGURED", "message": "Admin authentication is not configured."})
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


@auth_router.post("/login", response_model=AdminMe)
async def login(body: AdminLogin, response: Response, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.admin_username or not settings.admin_password_hash or not settings.admin_session_secret:
        raise HTTPException(503, detail={"code": "ADMIN_AUTH_NOT_CONFIGURED", "message": "Admin authentication is not configured."})
    valid = hmac.compare_digest(body.username, settings.admin_username)
    try:
        valid = password_hasher.verify(settings.admin_password_hash, body.password) and valid
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(401, detail={"code": "INVALID_ADMIN_CREDENTIALS", "message": "Username or password is incorrect."})
    raw_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=settings.admin_session_ttl_seconds)
    db.add(AdminSession(token_hash=_token_hash(raw_token), username=settings.admin_username, expires_at=expires))
    await db.commit()
    response.set_cookie("admin_session", raw_token, max_age=settings.admin_session_ttl_seconds, expires=expires, httponly=True, secure=settings.secure_admin_cookie, samesite="lax", path="/")
    return AdminMe(username=settings.admin_username)


@auth_router.post("/logout", status_code=204)
async def logout(response: Response, admin_session: str | None = Cookie(default=None), db: AsyncSession = Depends(get_db)):
    if admin_session:
        try:
            await db.execute(update(AdminSession).where(AdminSession.token_hash == _token_hash(admin_session), AdminSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
            await db.commit()
        except HTTPException:
            await db.rollback()
    response.delete_cookie("admin_session", path="/", httponly=True, secure=get_settings().secure_admin_cookie, samesite="lax")


async def require_admin(admin_session: str | None = Depends(admin_cookie_scheme), db: AsyncSession = Depends(get_db)) -> AdminSession:
    if not admin_session:
        raise HTTPException(401, detail={"code": "ADMIN_SESSION_REQUIRED", "message": "Administrator sign-in is required."})
    try:
        token_hash = _token_hash(admin_session)
    except HTTPException:
        raise
    now = datetime.now(timezone.utc)
    session = await db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash, AdminSession.revoked_at.is_(None), AdminSession.expires_at > now))
    if not session:
        raise HTTPException(401, detail={"code": "INVALID_ADMIN_SESSION", "message": "Administrator session is invalid or expired."})
    session.last_seen_at = now
    await db.commit()
    return session


protected_auth_router = APIRouter(prefix="/auth", tags=["admin authentication"], dependencies=[Depends(require_admin)])


@protected_auth_router.get("/me", response_model=AdminMe)
async def me(session: AdminSession = Depends(require_admin)):
    return AdminMe(username=session.username)
