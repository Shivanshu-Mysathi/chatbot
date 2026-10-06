def test_sessions_require_auth(client):
    assert client.get('/api/v1/sessions').status_code == 401
    assert client.get('/api/v1/sessions/00000000-0000-0000-0000-000000000000').status_code == 401
