import time
from collections import defaultdict, deque
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.config import get_settings

# Process-local only. Replace with shared Redis storage before running multiple instances.
_requests: dict[str, deque[float]] = defaultdict(deque)
async def rate_limit(request: Request, call_next):
    if request.url.path == '/api/v1/chat':
        now = time.monotonic(); key = request.client.host if request.client else 'unknown'
        bucket = _requests[key]
        while bucket and bucket[0] <= now - 60: bucket.popleft()
        if len(bucket) >= get_settings().rate_limit_per_minute:
            return JSONResponse(status_code=429, content={'error':{'code':'RATE_LIMIT_EXCEEDED','message':'Too many requests. Please try again shortly.'}})
        bucket.append(now)
    return await call_next(request)
