import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.auth import user_identity


def token(secret, claims, header=None):
    enc=lambda value:base64.urlsafe_b64encode(json.dumps(value,separators=(",",":")).encode()).decode().rstrip("=")
    first=enc(header or {"alg":"HS256","typ":"JWT"}); second=enc(claims)
    sig=base64.urlsafe_b64encode(hmac.new(secret.encode(),f"{first}.{second}".encode(),hashlib.sha256).digest()).decode().rstrip("=")
    return f"{first}.{second}.{sig}"


def test_signed_application_identity_claims(monkeypatch):
    monkeypatch.setattr(user_identity,"get_settings",lambda:SimpleNamespace(user_identity_jwt_secret="test-jwt-secret-that-is-at-least-32-bytes",user_identity_jwt_issuer="app",user_identity_jwt_audience="ai-chat",app_env="development"))
    signed=token("test-jwt-secret-that-is-at-least-32-bytes",{"sub":"u-7","email":"u@example.test","name":"Test User","iss":"app","aud":"ai-chat","exp":time.time()+60})
    identity=user_identity.validate_identity_token(signed)
    assert (identity.user_id,identity.email,identity.name)==("u-7","u@example.test","Test User")


def test_invalid_or_unconfigured_identity_rejected(monkeypatch):
    monkeypatch.setattr(user_identity,"get_settings",lambda:SimpleNamespace(user_identity_jwt_secret="this-is-a-strong-jwt-test-secret-value",user_identity_jwt_issuer=None,user_identity_jwt_audience=None,app_env="development"))
    with pytest.raises(HTTPException) as exc:user_identity.validate_identity_token("bad.token.value")
    assert exc.value.status_code==401
    monkeypatch.setattr(user_identity,"get_settings",lambda:SimpleNamespace(user_identity_jwt_secret=None,user_identity_jwt_issuer=None,user_identity_jwt_audience=None,app_env="development"))
    with pytest.raises(HTTPException) as exc:user_identity.validate_identity_token("bad.token.value")
    assert exc.value.detail["code"]=="IDENTITY_NOT_CONFIGURED"
