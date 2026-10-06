import secrets
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)

async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    expected = get_settings().chat_api_key
    if credentials is None:
        raise HTTPException(401, detail={'code':'MISSING_API_KEY','message':'A bearer API key is required.'})
    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(401, detail={'code':'INVALID_API_KEY','message':'The API key is invalid.'})
