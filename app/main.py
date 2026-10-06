from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from app.api.v1.router import router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import engine
from app.middleware.rate_limit import rate_limit
from app.services.ollama_service import OllamaError

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(); yield
    await engine.dispose()
app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().origins, allow_credentials=False, allow_methods=['GET','POST','DELETE'], allow_headers=['Authorization','Content-Type','X-Application-Identity'])
app.middleware('http')(rate_limit)
app.include_router(router, prefix='/api/v1')
@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and 'code' in detail:
        error = detail
    else:
        error = {'code':'HTTP_ERROR','message':str(detail)}
    return JSONResponse(status_code=exc.status_code, content={'error':error}, headers=exc.headers)
@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=jsonable_encoder({'error':{'code':'INVALID_REQUEST','message':'Request validation failed.','details':exc.errors()}}))
@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={'error':{'code':'DATABASE_UNAVAILABLE','message':'Database is temporarily unavailable.'}})
@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    import logging
    logging.getLogger(__name__).exception('Unhandled server error')
    return JSONResponse(status_code=500, content={'error':{'code':'INTERNAL_ERROR','message':'An unexpected server error occurred.'}})
@app.get('/health')
async def health(): return {'status':'ok'}
@app.get('/health/database')
async def database_health():
    try:
        async with engine.connect() as conn: await conn.execute(text('SELECT 1'))
        return {'status':'ok','database':'reachable'}
    except Exception: return JSONResponse(status_code=503, content={'error':{'code':'DATABASE_UNAVAILABLE','message':'Database is unavailable.'}})
@app.get('/health/ollama')
async def ollama_health():
    from app.services.ollama_service import OllamaService
    try:
        await OllamaService().check()
        return {'status':'ok','ollama':'reachable','model':get_settings().ollama_model}
    except OllamaError as exc:
        return JSONResponse(status_code=503, content={'error':{'code':exc.code,'message':exc.public_message}})
