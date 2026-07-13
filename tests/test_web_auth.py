import time
from web.auth import (
    create_session_secret,
    sign_session,
    verify_session,
    check_login_rate,
    record_login_failure,
    reset_rate_limits,
    COOKIE_NAME,
)


def test_create_session_secret_uses_configured():
    assert create_session_secret("fixed-secret-value") == "fixed-secret-value"


def test_create_session_secret_generates_when_empty():
    a = create_session_secret("")
    b = create_session_secret("")
    assert len(a) >= 32
    assert a != b  # random each call when empty


def test_sign_and_verify_session_roundtrip():
    secret = "unit-test-secret"
    token = sign_session(secret)
    assert verify_session(secret, token) is True
    assert verify_session(secret, token + "x") is False
    assert verify_session("other", token) is False


def test_login_rate_limit_blocks_after_failures():
    reset_rate_limits()
    ip = "203.0.113.9"
    for _ in range(10):
        assert check_login_rate(ip) is True
        record_login_failure(ip)
    assert check_login_rate(ip) is False


from fastapi.testclient import TestClient
from web.app import create_app
from web.auth import create_session_secret


def test_login_and_protected_route_pattern():
    app = create_app(full_ui=True)
    app.state.web_token = "secret-token"
    app.state.session_secret = create_session_secret("sess")
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.text == "OK"
    bad = client.post("/api/auth/login", json={"token": "wrong"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"token": "secret-token"})
    assert good.status_code == 200
    assert "eca_session" in good.cookies
