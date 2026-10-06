"""Validate signed application identity JWTs without assuming an AWS token contract.

The application backend supplies a compact HS256 JWT in X-Application-Identity.
Production use requires agreeing on issuer, audience, secret rotation, and claims.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.core.config import get_settings


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str | None = None
    name: str | None = None


def _decode_segment(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def validate_identity_token(token: str) -> AuthenticatedUser:
    settings = get_settings()
    secret = settings.user_identity_jwt_secret
    if not secret:
        raise HTTPException(401, detail={"code": "IDENTITY_NOT_CONFIGURED", "message": "Application identity validation is not configured."})
    if len(secret) < 32 or (settings.app_env.lower() in {"production", "prod"} and (not settings.user_identity_jwt_issuer or not settings.user_identity_jwt_audience)):
        raise HTTPException(503, detail={"code": "IDENTITY_NOT_CONFIGURED", "message": "Application identity validation requires a strong key, issuer, and audience configuration."})
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(_decode_segment(header_part))
        claims = json.loads(_decode_segment(payload_part))
        if header.get("alg") != "HS256" or header.get("typ", "JWT") != "JWT":
            raise ValueError("Unsupported JWT header")
        signed = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode_segment(signature_part)):
            raise ValueError("Invalid signature")
        now = int(time.time())
        if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] <= now:
            raise ValueError("Expired token")
        if claims.get("nbf", 0) > now:
            raise ValueError("Token not active")
        if settings.user_identity_jwt_issuer and claims.get("iss") != settings.user_identity_jwt_issuer:
            raise ValueError("Invalid issuer")
        audience = claims.get("aud")
        if settings.user_identity_jwt_audience and settings.user_identity_jwt_audience not in (audience if isinstance(audience, list) else [audience]):
            raise ValueError("Invalid audience")
        user_id = claims.get("sub")
        if not isinstance(user_id, str) or not user_id or len(user_id) > 255:
            raise ValueError("Missing subject")
        email = claims.get("email")
        name = claims.get("name")
        return AuthenticatedUser(user_id, email if isinstance(email, str) else None, name if isinstance(name, str) else None)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, detail={"code": "INVALID_USER_IDENTITY", "message": "The application identity token is invalid."}) from exc


async def get_authenticated_user(x_application_identity: str | None = Header(default=None, alias="X-Application-Identity")) -> AuthenticatedUser | None:
    """Return a verified user, or None for legacy anonymous chatbot clients."""
    if not x_application_identity:
        return None
    return validate_identity_token(x_application_identity)
