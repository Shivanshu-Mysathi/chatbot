import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from argon2 import PasswordHasher

from app.db.database import get_db
from app.db.models import AdminSession
from app.main import app


class Rows:
    def all(self): return []
    def first(self): return None
    def __iter__(self): return iter([])


class FakeDB:
    def __init__(self): self.added=[]; self.session=None; self.statements=[]
    def add(self, value):
        self.added.append(value)
        if isinstance(value, AdminSession): self.session=value
    async def commit(self): pass
    async def rollback(self): pass
    async def execute(self, statement): self.statements.append(statement); return Rows()
    async def stream(self, statement): self.statements.append(statement); return AsyncRows()
    async def scalar(self, statement):
        entity=statement.column_descriptions[0].get("entity") if statement.column_descriptions else None
        if entity is AdminSession: return self.session
        return 0
    async def get(self, *args): return None


class AsyncRows:
    def __aiter__(self): return self
    async def __anext__(self): raise StopAsyncIteration


@pytest.fixture
def admin_setup(client, monkeypatch):
    from app.api.v1.admin import security
    password_hash=PasswordHasher().hash("correct horse battery")
    settings=SimpleNamespace(admin_username="ops", admin_password_hash=password_hash,
        admin_session_secret="s"*48, admin_session_ttl_seconds=3600, secure_admin_cookie=False)
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    db=FakeDB()
    async def override_db(): yield db
    client.app.dependency_overrides[get_db]=override_db
    yield client,db
    client.app.dependency_overrides.clear()


def _login(client, username="ops", password="correct horse battery"):
    return client.post("/api/v1/admin/auth/login", json={"username":username,"password":password})


def test_admin_login_success_sets_httponly_cookie_and_no_token_json(admin_setup):
    client,db=admin_setup
    response=_login(client)
    assert response.status_code==200
    assert response.json()=={"username":"ops"}
    cookie=response.headers["set-cookie"]
    assert "admin_session=" in cookie and "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    assert "token" not in response.json()
    assert len(db.added)==1 and len(db.added[0].token_hash)==64
    assert db.added[0].token_hash != cookie.split("admin_session=",1)[1].split(";",1)[0]


def test_admin_login_wrong_password(admin_setup):
    client,_=admin_setup
    response=_login(client,password="wrong")
    assert response.status_code==401
    assert response.json()["error"]["code"]=="INVALID_ADMIN_CREDENTIALS"


def test_admin_missing_and_invalid_session(admin_setup):
    client,_=admin_setup
    assert client.get("/api/v1/admin/auth/me").status_code==401
    response=client.get("/api/v1/admin/dashboard",headers={"Cookie":"admin_session=invalid"})
    assert response.status_code==401


def test_admin_me_dashboard_query_pagination_users_sessions(admin_setup):
    client,_=admin_setup
    login=_login(client)
    cookie=login.headers["set-cookie"].split(";",1)[0]
    assert client.get("/api/v1/admin/auth/me",headers={"Cookie":cookie}).json()=={"username":"ops"}
    assert client.get("/api/v1/admin/dashboard",headers={"Cookie":cookie}).status_code==200
    q=client.get("/api/v1/admin/queries?page=2&page_size=5&search=pnr&date_from=2026-01-01",headers={"Cookie":cookie})
    assert q.status_code==200 and q.json()=={"items":[],"page":2,"page_size":5,"total":0,"pages":0}
    assert client.get("/api/v1/admin/users?page_size=10",headers={"Cookie":cookie}).status_code==200
    assert client.get("/api/v1/admin/sessions?page_size=10",headers={"Cookie":cookie}).status_code==200
    schema=app.openapi()
    assert "AdminSessionCookie" in schema["components"]["securitySchemes"]
    assert {"AdminSessionCookie": []} in schema["paths"]["/api/v1/admin/dashboard"]["get"]["security"]


def test_admin_logout_revokes_and_clears_cookie(admin_setup):
    client,db=admin_setup
    login=_login(client); cookie=login.headers["set-cookie"].split(";",1)[0]
    result=client.post("/api/v1/admin/auth/logout",headers={"Cookie":cookie})
    assert result.status_code==204
    assert 'admin_session=""' in result.headers["set-cookie"]
    assert db.statements


def test_admin_query_detail_and_session_detail_not_found(admin_setup):
    client,_=admin_setup
    login=_login(client); cookie=login.headers["set-cookie"].split(";",1)[0]
    assert client.get(f"/api/v1/admin/queries/{uuid.uuid4()}",headers={"Cookie":cookie}).status_code==404
    assert client.get(f"/api/v1/admin/sessions/{uuid.uuid4()}",headers={"Cookie":cookie}).status_code==404


def test_admin_date_search_stats_and_csv_export(admin_setup):
    client,db=admin_setup
    login=_login(client); cookie=login.headers["set-cookie"].split(";",1)[0]
    response=client.get("/api/v1/admin/queries?search=pnr&user_id=u-2&date_from=2026-02-01&date_to=2026-02-28",headers={"Cookie":cookie})
    assert response.status_code==200
    compiled=" ".join(str(statement) for statement in db.statements)
    bound_values=str([statement.compile().params for statement in db.statements])
    assert "lower(" in compiled and "created_at" in compiled and "%pnr%" in bound_values
    assert client.get("/api/v1/admin/stats?date_from=2026-02-01&date_to=2026-02-28",headers={"Cookie":cookie}).status_code==200
    export=client.get("/api/v1/admin/export/queries?search=pnr",headers={"Cookie":cookie})
    assert export.status_code==200 and "text/csv" in export.headers["content-type"]
    assert "user_id,user_email,user_name,query,timestamp" in export.text


def test_chatbot_api_key_does_not_authorize_admin(admin_setup):
    client,_=admin_setup
    response=client.get("/api/v1/admin/dashboard",headers={"Authorization":"Bearer test-secret"})
    assert response.status_code==401
