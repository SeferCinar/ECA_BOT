from __future__ import annotations

import hmac
import secrets
import time
from typing import Dict, List, Optional

from fastapi import Cookie, Header, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE_NAME = "eca_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
MAX_FAILURES = 10
FAILURE_WINDOW_SEC = 60

_failures: Dict[str, List[float]] = {}


def reset_rate_limits() -> None:
    _failures.clear()


def create_session_secret(configured: str) -> str:
    configured = (configured or "").strip()
    if configured:
        return configured
    return secrets.token_urlsafe(32)


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="eca-web-session")


def sign_session(secret: str) -> str:
    return _serializer(secret).dumps({"ok": True})


def verify_session(secret: str, value: str) -> bool:
    if not value:
        return False
    try:
        _serializer(secret).loads(value, max_age=SESSION_MAX_AGE)
        return True
    except BadSignature:
        return False
    except Exception:
        return False


def check_login_rate(ip: str) -> bool:
    now = time.time()
    window = _failures.get(ip, [])
    window = [t for t in window if now - t < FAILURE_WINDOW_SEC]
    _failures[ip] = window
    return len(window) < MAX_FAILURES


def record_login_failure(ip: str) -> None:
    _failures.setdefault(ip, []).append(time.time())


def tokens_match(expected: str, provided: str) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


async def require_auth(
    request: Request,
    eca_session: Optional[str] = Cookie(default=None, alias=COOKIE_NAME),
    authorization: Optional[str] = Header(default=None),
) -> None:
    secret = request.app.state.session_secret
    web_token = request.app.state.web_token
    if not web_token:
        raise HTTPException(status_code=503, detail={"error": "Web UI disabled", "code": "UI_DISABLED"})

    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
        if tokens_match(web_token, bearer):
            return

    if eca_session and secret and verify_session(secret, eca_session):
        return

    raise HTTPException(status_code=401, detail={"error": "Unauthorized", "code": "UNAUTHORIZED"})
