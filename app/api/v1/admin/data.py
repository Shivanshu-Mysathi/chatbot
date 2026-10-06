from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.v1.admin.security import require_admin
from app.db.database import get_db
from app.db.models import AdminSession, ChatMessage, ChatSession

router = APIRouter(dependencies=[Depends(require_admin)])


def _bounds(date_from: date | None, date_to: date | None):
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc) if date_to else None
    if start and end and start >= end:
        raise HTTPException(422, detail={"code": "INVALID_DATE_RANGE", "message": "date_from must not be after date_to."})
    return start, end


def _page(page: int, page_size: int):
    return (page - 1) * page_size


def _page_result(items, page: int, page_size: int, total: int):
    return {"items": items, "page": page, "page_size": page_size, "total": total, "pages": (total + page_size - 1) // page_size}


def _query_stmt(*, search: str | None = None, user_id: str | None = None, session_id: uuid.UUID | None = None,
                date_from: date | None = None, date_to: date | None = None, include_response: bool = False):
    message = aliased(ChatMessage, name="query_message")
    session = aliased(ChatSession, name="query_session")
    assistant = aliased(ChatMessage, name="query_answer")
    answer_time = (select(assistant.response_time_ms).where(assistant.session_id == message.session_id,
        assistant.role == "assistant", assistant.created_at >= message.created_at)
        .order_by(assistant.created_at, assistant.id).limit(1).scalar_subquery())
    answer_model = (select(assistant.model).where(assistant.session_id == message.session_id,
        assistant.role == "assistant", assistant.created_at >= message.created_at)
        .order_by(assistant.created_at, assistant.id).limit(1).scalar_subquery())
    selected = [message, session, answer_time.label("response_time_ms"), answer_model.label("model")]
    if include_response:
        answer_content = (select(assistant.content).where(assistant.session_id == message.session_id,
            assistant.role == "assistant", assistant.created_at >= message.created_at)
            .order_by(assistant.created_at, assistant.id).limit(1).scalar_subquery())
        selected.append(answer_content.label("assistant_response"))
    stmt = select(*selected).join(session, session.id == message.session_id).where(message.role == "user")
    start, end = _bounds(date_from, date_to)
    if start: stmt = stmt.where(message.created_at >= start)
    if end: stmt = stmt.where(message.created_at < end)
    if user_id: stmt = stmt.where(session.user_id == user_id)
    if session_id: stmt = stmt.where(session.id == session_id)
    if search:
        pattern = f"%{search}%"
        predicates = [message.content.ilike(pattern), session.user_id.ilike(pattern), session.user_name.ilike(pattern), session.user_email.ilike(pattern)]
        try: predicates.append(session.id == uuid.UUID(search))
        except ValueError: pass
        stmt = stmt.where(or_(*predicates))
    return stmt, message, session


def _query_dict(message: ChatMessage, session: ChatSession, response_time_ms, model, assistant_response=None, detail=False):
    value = {"id": str(message.id), "message_id": str(message.id), "session_id": str(session.id), "user_id": session.user_id,
        "user_name": session.user_name, "user_email": session.user_email, "query": message.content,
        "created_at": message.created_at, "timestamp": message.created_at, "response_time_ms": response_time_ms,
        "model": model, "rag_used": message.rag_used}
    if detail:
        value.update(assistant_response=assistant_response, retrieved_chunks=message.retrieved_chunks or [])
    return value


async def _query_page(db, *, page, page_size, search=None, user_id=None, session_id=None, date_from=None, date_to=None, sort="created_at", order="desc"):
    stmt, message, _ = _query_stmt(search=search, user_id=user_id, session_id=session_id, date_from=date_from, date_to=date_to)
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    sort_expr = message.created_at if sort == "created_at" else message.content if sort == "query" else message.response_time_ms
    stmt = stmt.order_by(sort_expr.asc() if order == "asc" else sort_expr.desc(), message.id.desc()).offset(_page(page, page_size)).limit(page_size)
    rows = (await db.execute(stmt)).all()
    items = [_query_dict(row[0], row[1], row[2], row[3]) for row in rows]
    return _page_result(items, page, page_size, total)


@router.get("/dashboard")
async def dashboard(range: Literal["today", "yesterday", "7d", "30d", "all"] = "30d", db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    start = {"today": today_start, "yesterday": today_start - timedelta(days=1), "7d": now - timedelta(days=7), "30d": now - timedelta(days=30), "all": None}[range]
    end = today_start if range == "yesterday" else today_start + timedelta(days=1) if range == "today" else None
    user_query = select(ChatSession.user_id).join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatMessage.role == "user", ChatSession.user_id.is_not(None))
    total_users = await db.scalar(select(func.count()).select_from(user_query.distinct().subquery())) or 0
    query_base = select(func.count(ChatMessage.id)).where(ChatMessage.role == "user")
    total_queries = await db.scalar(query_base) or 0
    async def count_since(dt):
        stmt = query_base.where(ChatMessage.created_at >= dt) if dt else query_base
        return await db.scalar(stmt) or 0
    active_stmt = select(func.count(distinct(ChatSession.user_id))).join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatMessage.role == "user", ChatSession.user_id.is_not(None))
    if start: active_stmt = active_stmt.where(ChatMessage.created_at >= start)
    if end: active_stmt = active_stmt.where(ChatMessage.created_at < end)
    active_users = await db.scalar(active_stmt) or 0
    avg_stmt = select(func.avg(ChatMessage.response_time_ms)).where(ChatMessage.role == "assistant", ChatMessage.response_time_ms.is_not(None))
    if start: avg_stmt = avg_stmt.where(ChatMessage.created_at >= start)
    if end: avg_stmt = avg_stmt.where(ChatMessage.created_at < end)
    avg_response = await db.scalar(avg_stmt)
    rag_total_stmt = select(func.count(ChatMessage.id)).where(ChatMessage.role == "user")
    rag_used_stmt = select(func.count(ChatMessage.id)).where(ChatMessage.role == "user", ChatMessage.rag_used.is_(True))
    if start:
        rag_total_stmt = rag_total_stmt.where(ChatMessage.created_at >= start); rag_used_stmt = rag_used_stmt.where(ChatMessage.created_at >= start)
    if end:
        rag_total_stmt = rag_total_stmt.where(ChatMessage.created_at < end); rag_used_stmt = rag_used_stmt.where(ChatMessage.created_at < end)
    rag_total = await db.scalar(rag_total_stmt) or 0
    rag_used = await db.scalar(rag_used_stmt) or 0
    total_sessions = await db.scalar(select(func.count(ChatSession.id))) or 0
    recent = await _query_page(db, page=1, page_size=8, date_from=None if range == "all" else (start.date() if start else None), date_to=(start.date() if range == "yesterday" and start else None))
    utc_day = func.date(func.timezone("UTC", ChatMessage.created_at))
    daily_stmt = select(utc_day.label("day"), func.count(ChatMessage.id).label("count")).where(ChatMessage.role == "user")
    if start: daily_stmt = daily_stmt.where(ChatMessage.created_at >= start)
    if end: daily_stmt = daily_stmt.where(ChatMessage.created_at < end)
    daily_rows = (await db.execute(daily_stmt.group_by("day").order_by("day"))).all()
    return {"total_users": total_users, "total_queries": total_queries, "queries_today": await count_since(today_start),
        "queries_week": await count_since(now - timedelta(days=7)), "queries_month": await count_since(now - timedelta(days=30)),
        "queries_last_7_days": await count_since(now - timedelta(days=7)), "queries_last_30_days": await count_since(now - timedelta(days=30)),
        "total_sessions": total_sessions, "active_users": active_users, "avg_response_time_ms": float(avg_response or 0),
        "average_response_time_ms": float(avg_response or 0), "rag_usage_percent": (100.0 * rag_used / rag_total) if rag_total else 0.0,
        "queries_by_day": [{"date": str(day), "count": count} for day, count in daily_rows], "recent_queries": recent["items"]}


@router.get("/queries")
async def queries(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str | None = Query(None, max_length=200),
    user_id: str | None = Query(None, max_length=255), session_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
    sort: Literal["created_at", "query", "response_time_ms"] = "created_at", order: Literal["asc", "desc"] = "desc", db: AsyncSession = Depends(get_db)):
    return await _query_page(db, page=page, page_size=page_size, search=search, user_id=user_id, session_id=session_id, date_from=date_from, date_to=date_to, sort=sort, order=order)


@router.get("/queries/{message_id}")
async def query_detail(message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    stmt, message, _ = _query_stmt(include_response=True)
    row = (await db.execute(stmt.where(message.id == message_id).limit(1))).first()
    if not row: raise HTTPException(404, detail={"code": "QUERY_NOT_FOUND", "message": "Query was not found."})
    m, s, latency, model, answer = row
    return _query_dict(m, s, latency, model, answer, detail=True)


@router.get("/users")
async def users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str | None = Query(None, max_length=200), date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db)):
    start, end = _bounds(date_from, date_to)
    stmt = select(ChatSession.user_id, func.max(ChatSession.user_name).label("user_name"), func.max(ChatSession.user_email).label("user_email"),
        func.count(ChatMessage.id).label("total_queries"), func.count(distinct(ChatSession.id)).label("total_sessions"),
        func.min(ChatMessage.created_at).label("first_seen"), func.max(ChatMessage.created_at).label("last_seen"))
    stmt = stmt.join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatSession.user_id.is_not(None), ChatMessage.role == "user")
    if start: stmt = stmt.where(ChatMessage.created_at >= start)
    if end: stmt = stmt.where(ChatMessage.created_at < end)
    if search:
        pat = f"%{search}%"
        stmt = stmt.where(or_(ChatSession.user_id.ilike(pat), ChatSession.user_name.ilike(pat), ChatSession.user_email.ilike(pat)))
    grouped = stmt.group_by(ChatSession.user_id).subquery()
    latency_stmt = select(ChatSession.user_id.label("user_id"), func.avg(ChatMessage.response_time_ms).label("average_response_time_ms")).join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatMessage.role == "assistant", ChatMessage.response_time_ms.is_not(None))
    if start: latency_stmt = latency_stmt.where(ChatMessage.created_at >= start)
    if end: latency_stmt = latency_stmt.where(ChatMessage.created_at < end)
    latency = latency_stmt.group_by(ChatSession.user_id).subquery()
    total = await db.scalar(select(func.count()).select_from(grouped)) or 0
    rows = (await db.execute(select(grouped, latency.c.average_response_time_ms).outerjoin(latency, latency.c.user_id == grouped.c.user_id).order_by(grouped.c.last_seen.desc()).offset(_page(page, page_size)).limit(page_size))).all()
    items = [{"user_id": r.user_id, "user_name": r.user_name, "user_email": r.user_email, "total_queries": r.total_queries,
        "total_sessions": r.total_sessions, "first_seen": r.first_seen, "last_seen": r.last_seen, "last_query": r.last_seen,
        "first_seen_at": r.first_seen, "average_response_time_ms": float(r.average_response_time_ms or 0), "avg_response_time_ms": float(r.average_response_time_ms or 0)} for r in rows]
    return _page_result(items, page, page_size, total)


async def _user_summary(db: AsyncSession, user_id: str):
    stmt = select(ChatSession.user_id, func.max(ChatSession.user_name).label("user_name"), func.max(ChatSession.user_email).label("user_email"),
        func.count(ChatMessage.id).label("total_queries"), func.count(distinct(ChatSession.id)).label("total_sessions"),
        func.min(ChatMessage.created_at).label("first_seen"), func.max(ChatMessage.created_at).label("last_seen"))
    stmt = stmt.join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatSession.user_id == user_id, ChatMessage.role == "user")
    grouped = stmt.group_by(ChatSession.user_id).subquery()
    latency = select(ChatSession.user_id.label("user_id"), func.avg(ChatMessage.response_time_ms).label("average_response_time_ms")).join(ChatMessage, ChatMessage.session_id == ChatSession.id).where(ChatMessage.role == "assistant", ChatMessage.response_time_ms.is_not(None)).group_by(ChatSession.user_id).subquery()
    r = (await db.execute(select(grouped, latency.c.average_response_time_ms).outerjoin(latency, latency.c.user_id == grouped.c.user_id).where(grouped.c.user_id == user_id))).first()
    if not r: return None
    return {"user_id": r.user_id, "user_name": r.user_name, "user_email": r.user_email, "total_queries": r.total_queries, "total_sessions": r.total_sessions,
        "first_seen": r.first_seen, "last_seen": r.last_seen, "last_query": r.last_seen, "first_seen_at": r.first_seen,
        "average_response_time_ms": float(r.average_response_time_ms or 0), "avg_response_time_ms": float(r.average_response_time_ms or 0)}


@router.get("/users/{user_id}")
async def user_detail(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await _user_summary(db, user_id)
    if result is None: raise HTTPException(404, detail={"code": "USER_NOT_FOUND", "message": "User was not found."})
    return result


@router.get("/users/{user_id}/queries")
async def user_queries(user_id: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db)):
    return await _query_page(db, page=page, page_size=page_size, user_id=user_id, date_from=date_from, date_to=date_to)


@router.get("/sessions")
async def sessions(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), search: str | None = Query(None, max_length=200), user_id: str | None = Query(None, max_length=255), date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db)):
    start, end = _bounds(date_from, date_to)
    query_count = select(func.count(ChatMessage.id)).where(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "user").correlate(ChatSession).scalar_subquery()
    message_count = select(func.count(ChatMessage.id)).where(ChatMessage.session_id == ChatSession.id).correlate(ChatSession).scalar_subquery()
    stmt = select(ChatSession, message_count.label("message_count"), query_count.label("user_query_count"))
    if start: stmt = stmt.where(ChatSession.created_at >= start)
    if end: stmt = stmt.where(ChatSession.created_at < end)
    if user_id: stmt = stmt.where(ChatSession.user_id == user_id)
    if search:
        pat = f"%{search}%"
        message_match = exists(select(1).where(ChatMessage.session_id == ChatSession.id, ChatMessage.content.ilike(pat)))
        predicates = [ChatSession.user_id.ilike(pat), ChatSession.user_email.ilike(pat), ChatSession.user_name.ilike(pat), message_match]
        try: predicates.append(ChatSession.id == uuid.UUID(search))
        except ValueError: pass
        stmt = stmt.where(or_(*predicates))
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = (await db.execute(stmt.order_by(ChatSession.updated_at.desc()).offset(_page(page, page_size)).limit(page_size))).all()
    items = [{"id": str(s.id), "session_id": str(s.id), "user_id": s.user_id, "user_name": s.user_name, "user_email": s.user_email,
        "created_at": s.created_at, "updated_at": s.updated_at, "message_count": mc, "query_count": qc, "user_query_count": qc} for s, mc, qc in rows]
    return _page_result(items, page, page_size, total)


@router.get("/sessions/{session_id}")
async def session_detail(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if session is None: raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "Session was not found."})
    messages = (await db.execute(select(ChatMessage.id, ChatMessage.role, ChatMessage.content, ChatMessage.model, ChatMessage.response_time_ms, ChatMessage.created_at, ChatMessage.rag_used, ChatMessage.retrieved_chunks).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.id))).all()
    return {"id": str(session.id), "session_id": str(session.id), "user_id": session.user_id, "user_name": session.user_name, "user_email": session.user_email,
        "created_at": session.created_at, "updated_at": session.updated_at, "message_count": len(messages), "query_count": sum(m.role == "user" for m in messages),
        "messages": [{"id": str(m.id), "role": m.role, "content": m.content, "model": m.model, "response_time_ms": m.response_time_ms, "created_at": m.created_at, "rag_used": m.rag_used, "retrieved_chunks": m.retrieved_chunks or []} for m in messages]}


@router.get("/stats")
async def stats(date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db)):
    start, end = _bounds(date_from, date_to)
    utc_day = func.date(func.timezone("UTC", ChatMessage.created_at))
    per_day = await db.execute(select(utc_day.label("day"), func.count(ChatMessage.id)).where(ChatMessage.role == "user", *([ChatMessage.created_at >= start] if start else []), *([ChatMessage.created_at < end] if end else [])).group_by("day").order_by("day"))
    active = await db.execute(select(utc_day.label("day"), func.count(distinct(ChatSession.user_id))).join(ChatSession, ChatSession.id == ChatMessage.session_id).where(ChatMessage.role == "user", ChatSession.user_id.is_not(None), *([ChatMessage.created_at >= start] if start else []), *([ChatMessage.created_at < end] if end else [])).group_by("day").order_by("day"))
    latency = await db.execute(select(utc_day.label("day"), func.avg(ChatMessage.response_time_ms)).where(ChatMessage.role == "assistant", ChatMessage.response_time_ms.is_not(None), *([ChatMessage.created_at >= start] if start else []), *([ChatMessage.created_at < end] if end else [])).group_by("day").order_by("day"))
    hourly = await db.execute(select(func.extract("hour", func.timezone("UTC", ChatMessage.created_at)).label("hour"), func.count(ChatMessage.id)).where(ChatMessage.role == "user", *([ChatMessage.created_at >= start] if start else []), *([ChatMessage.created_at < end] if end else [])).group_by("hour").order_by("hour"))
    return {"queries_per_day": [{"date": str(d), "count": n} for d, n in per_day], "active_users_per_day": [{"date": str(d), "count": n} for d, n in active],
        "average_response_time_per_day": [{"date": str(d), "average_response_time_ms": float(n or 0)} for d, n in latency], "queries_by_hour": [{"hour": int(h), "count": n} for h, n in hourly]}


@router.get("/export/queries")
async def export_queries(search: str | None = Query(None, max_length=200), user_id: str | None = Query(None, max_length=255), session_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None, db: AsyncSession = Depends(get_db)):
    stmt, message, _ = _query_stmt(search=search, user_id=user_id, session_id=session_id, date_from=date_from, date_to=date_to)
    writer_buffer = io.StringIO(newline="")
    writer = csv.writer(writer_buffer)
    writer.writerow(["user_id", "user_email", "user_name", "query", "timestamp", "session_id", "response_time_ms", "model", "rag_used", "message_id"])
    result = await db.stream(stmt.order_by(message.created_at.desc(), message.id.desc()).execution_options(yield_per=500))
    async def rows():
        yield writer_buffer.getvalue()
        async for m, s, latency, model in result:
            row_buffer = io.StringIO(newline="")
            safe = lambda value: "'" + value if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"} else value
            csv.writer(row_buffer).writerow([safe(s.user_id or ""), safe(s.user_email or ""), safe(s.user_name or ""), safe(m.content), m.created_at.isoformat(), str(s.id), latency if latency is not None else "", safe(model or ""), m.rag_used if m.rag_used is not None else "", str(m.id)])
            yield row_buffer.getvalue()
    return StreamingResponse(rows(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=chat-query-export.csv"})
