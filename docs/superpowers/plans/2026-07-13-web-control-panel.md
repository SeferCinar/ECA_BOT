# Web Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a same-process FastAPI web control panel with token auth so the bot owner can join voice, play/search music, control the queue, and manage playlists/library from a dark Spotify/Discord-style UI.

**Architecture:** Replace the optional `HTTPServer` health handler with FastAPI+uvicorn on the bot asyncio loop. A `MusicService` resolves guild, wraps `MusicPlayer` / `PlaylistManager` / `MusicDownloader` without Discord `Interaction`. Vanilla static SPA talks REST + WebSocket; session cookie or Bearer token auth.

**Tech Stack:** Python 3.8+, discord.py, FastAPI, uvicorn[standard], vanilla HTML/CSS/JS, pytest, itsdangerous (via starlette for signed cookies) or hmac+stdlib

## Global Constraints

- Same Python process as Discord bot; single asyncio event loop for bot + web
- `WEB_UI_TOKEN` non-empty enables full UI+API; else `ENABLE_HEALTH_SERVER` enables health-only; else no HTTP
- Port: `PORT` or `HEALTHCHECK_PORT` or `8080`
- `/health` and `/healthz` unauthenticated when HTTP runs
- Default guild: explicit `guild_id` → `WEB_UI_GUILD_ID` → sole guild → 400
- Dark UI: bg `#0d0d12`, cards `#1a1a24`, accent `#5865F2`
- No Discord OAuth, no multi-guild picker UI, no file upload, no frontend build step
- Library play: basename under `MUSIC_DIR` only (reject path traversal)
- Error JSON: `{ "error": "...", "code": "..." }`
- Spec: `docs/superpowers/specs/2026-07-13-web-control-panel-design.md`

## File Structure

| Path | Responsibility |
|------|----------------|
| `web/__init__.py` | Package marker; export `create_app`, `start_web_server` |
| `web/app.py` | FastAPI factory: health, mount static, include routers, full vs health-only mode |
| `web/auth.py` | Token verify, session cookie, Bearer, login rate limit, dependency `require_auth` |
| `web/service.py` | `MusicService`, guild resolution, state snapshots, play/search/control/playlist/library |
| `web/routes/api.py` | REST endpoints |
| `web/routes/ws.py` | WebSocket `/ws/state` |
| `web/static/index.html` | Login + control panel shell |
| `web/static/css/app.css` | Dark music-player styles |
| `web/static/js/app.js` | Auth, tabs, API client, WS/polling, player bar |
| `config.py` | `WEB_UI_*` settings |
| `music.py` | Interaction-optional playback (voice_client on player; optional notify) |
| `bot.py` | Remove HTTPServer health; start FastAPI; inject bot/players into web |
| `requirements.txt` | fastapi, uvicorn[standard] |
| `.env.example`, `README.md` | Document web UI |
| `tests/test_web_auth.py` | Auth unit tests |
| `tests/test_web_service.py` | Guild resolution / snapshot helpers |
| `tests/test_web_api.py` | API smoke with TestClient + mocks |

---

### Task 1: Config, dependencies, FastAPI shell, bot lifecycle

**Files:**
- Modify: `requirements.txt`
- Modify: `config.py`
- Create: `web/__init__.py`
- Create: `web/app.py`
- Modify: `bot.py` (remove `_HealthHandler` / `_start_health_server_if_enabled`; call web starter from `on_ready` or `__main__`)
- Test: manual health curl after run (full automated health test in Task 2+)

**Interfaces:**
- Produces: `Config.WEB_UI_TOKEN: str`, `Config.WEB_UI_GUILD_ID: Optional[str]`, `Config.WEB_UI_SESSION_SECRET: str`, `Config.web_http_enabled() -> str` mode `"full"|"health"|"off"`, `Config.web_port() -> int`
- Produces: `web.app.create_app(*, bot=None, full_ui: bool) -> FastAPI`
- Produces: `web.start_web_server(app, host, port) -> asyncio.Task` (uvicorn on running loop)

- [ ] **Step 1: Add dependencies**

Append to `requirements.txt`:

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
pytest>=7.0.0
```

(`httpx` needed by FastAPI `TestClient`.)

- [ ] **Step 2: Extend Config**

In `config.py`, add to `Config`:

```python
    # Web control panel
    WEB_UI_TOKEN = os.getenv('WEB_UI_TOKEN', '').strip()
    WEB_UI_GUILD_ID = os.getenv('WEB_UI_GUILD_ID', '').strip() or None
    WEB_UI_SESSION_SECRET = os.getenv('WEB_UI_SESSION_SECRET', '').strip()

    @classmethod
    def web_port(cls) -> int:
        port_str = (os.getenv('PORT') or os.getenv('HEALTHCHECK_PORT') or '8080').strip()
        try:
            return int(port_str)
        except ValueError:
            return 8080

    @classmethod
    def web_http_mode(cls) -> str:
        """Return 'full', 'health', or 'off'."""
        if cls.WEB_UI_TOKEN:
            return 'full'
        enabled = os.getenv('ENABLE_HEALTH_SERVER', '').strip().lower() in ('1', 'true', 'yes', 'on')
        return 'health' if enabled else 'off'
```

- [ ] **Step 3: Create minimal FastAPI app**

`web/__init__.py`:

```python
from web.app import create_app, start_web_server

__all__ = ["create_app", "start_web_server"]
```

`web/app.py`:

```python
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(*, bot: Any = None, full_ui: bool = False) -> FastAPI:
    app = FastAPI(title="ECA_BOT Web UI", docs_url=None, redoc_url=None)
    app.state.bot = bot
    app.state.full_ui = full_ui
    app.state.music_service = None  # set by bot after MusicService exists
    app.state.session_secret = None
    app.state.web_token = None

    @app.get("/health")
    @app.get("/healthz")
    async def health():
        return PlainTextResponse("OK")

    if full_ui and STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


async def start_web_server(app: FastAPI, host: str = "0.0.0.0", port: int = 8080):
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()
```

Note: mounting static at `/` last is intentional after API routes are included in later tasks. For this task only health matters; if static mount steals routes, include API routers **before** static mount in later tasks. **Rule for all later tasks:** register `/api` and `/ws` routes on `app` before `app.mount("/", StaticFiles(...))`.

- [ ] **Step 4: Wire bot.py**

Remove `BaseHTTPRequestHandler`, `HTTPServer`, `_HealthHandler`, `_start_health_server_if_enabled`.

Replace `__main__` block:

```python
if __name__ == '__main__':
    if not Config.TOKEN:
        print("❌ DISCORD_TOKEN bulunamadı. Coolify -> Environment Variables bölümüne DISCORD_TOKEN ekleyin.", flush=True)
        raise SystemExit(1)

    @bot.event
    async def setup_hook():
        mode = Config.web_http_mode()
        if mode == 'off':
            print("ℹ️ Web/health HTTP kapalı (WEB_UI_TOKEN veya ENABLE_HEALTH_SERVER yok)", flush=True)
            return
        from web.app import create_app, start_web_server
        full = mode == 'full'
        app = create_app(bot=bot, full_ui=full)
        app.state.web_token = Config.WEB_UI_TOKEN
        # session secret filled in Task 2
        port = Config.web_port()
        bot.loop.create_task(start_web_server(app, port=port))
        print(f"✅ HTTP sunucu ({mode}): http://0.0.0.0:{port}/health", flush=True)

    bot.run(Config.TOKEN)
```

**Important:** `discord.py` 2.x supports `setup_hook` on Bot. If this codebase’s discord version calls setup_hook, use it. If not available, start the task inside `on_ready` with a guard:

```python
_web_started = False

@bot.event
async def on_ready():
    global _web_started
    # ... existing sync code ...
    if not _web_started:
        _web_started = True
        await _maybe_start_web()
```

Prefer `setup_hook` when present so HTTP is up before ready events pile up.

- [ ] **Step 5: Placeholder static (full mode)**

Create `web/static/index.html`:

```html
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <title>ECA_BOT</title>
</head>
<body style="background:#0d0d12;color:#eee;font-family:sans-serif;padding:2rem">
  <h1>ECA_BOT Web UI</h1>
  <p>Shell OK — auth ve panel sonraki tasklarda.</p>
</body>
</html>
```

- [ ] **Step 6: Smoke check**

Run with env `WEB_UI_TOKEN=test` and valid/invalid Discord token as available. If Discord token missing, unit-test only create_app:

```bash
python -c "from web.app import create_app; app=create_app(full_ui=False); print([r.path for r in app.routes])"
```

Expected: paths include `/health`.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt config.py web bot.py
git commit -m "feat(web): FastAPI shell and health endpoint on bot process"
```

---

### Task 2: Auth (login, session cookie, Bearer, rate limit)

**Files:**
- Create: `web/auth.py`
- Modify: `web/app.py` (wire auth routes when full_ui; set session secret)
- Create: `tests/test_web_auth.py`
- Create: `tests/conftest.py` (optional)

**Interfaces:**
- Consumes: `Config.WEB_UI_TOKEN`, `Config.WEB_UI_SESSION_SECRET`
- Produces:
  - `create_session_secret(configured: str) -> str`
  - `sign_session(secret: str) -> str` / `verify_session(secret: str, value: str) -> bool`
  - `check_login_rate(ip: str) -> bool` (True if allowed)
  - `record_login_failure(ip: str) -> None`
  - `async def require_auth(request) -> None` FastAPI dependency raising 401
  - Cookie name: `eca_session`
  - Login body: `{ "token": "..." }`

- [ ] **Step 1: Write failing tests**

`tests/test_web_auth.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_web_auth.py -v
```

Expected: import errors / failures.

- [ ] **Step 3: Implement `web/auth.py`**

```python
from __future__ import annotations

import hmac
import hashlib
import secrets
import time
from typing import Dict, List, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request
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
```

Add `itsdangerous` to `requirements.txt` if not pulled in by starlette (Starlette includes it; if import fails, pin `itsdangerous>=2.0`).

- [ ] **Step 4: Auth routes in app (full_ui only)**

In `create_app`, when `full_ui`:

```python
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from web.auth import (
        COOKIE_NAME,
        check_login_rate,
        record_login_failure,
        require_auth,
        sign_session,
        tokens_match,
    )

    class LoginBody(BaseModel):
        token: str

    @app.post("/api/auth/login")
    async def login(body: LoginBody, request: Request):
        ip = request.client.host if request.client else "unknown"
        if not check_login_rate(ip):
            return JSONResponse(
                status_code=429,
                content={"error": "Too many attempts", "code": "RATE_LIMITED"},
            )
        if not tokens_match(app.state.web_token or "", body.token):
            record_login_failure(ip)
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid token", "code": "INVALID_TOKEN"},
            )
        value = sign_session(app.state.session_secret)
        resp = JSONResponse({"ok": True})
        resp.set_cookie(
            COOKIE_NAME,
            value,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
            path="/",
        )
        return resp

    @app.post("/api/auth/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE_NAME, path="/")
        return resp
```

In bot setup when creating app:

```python
from web.auth import create_session_secret
app.state.session_secret = create_session_secret(Config.WEB_UI_SESSION_SECRET)
```

- [ ] **Step 5: API smoke test with TestClient**

Add to `tests/test_web_auth.py`:

```python
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
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
pytest tests/test_web_auth.py -v
```

- [ ] **Step 7: Commit**

```bash
git add web/auth.py web/app.py requirements.txt tests/
git commit -m "feat(web): token login, session cookie, and rate limit"
```

---

### Task 3: MusicPlayer interaction-optional refactor

**Files:**
- Modify: `music.py`
- Create: `tests/test_music_player_web.py` (lightweight, no real Discord voice)

**Interfaces:**
- Produces:
  - `WebUser` simple object: `id`, `name`, `mention` property → `` `Web UI` `` or name
  - `MusicPlayer` methods accept `interaction=None` when `self.voice_client` / guild voice already set
  - `MusicPlayer.set_voice_client(vc)` 
  - `MusicPlayer.snapshot() -> dict` with `current`, `queue`, `volume`, `is_playing`, `is_paused`
  - Messaging no-ops when interaction is None (or accepts optional callback)
  - `play_next` after-callback must not require a live Interaction; use stored guild reference / voice_client

**Why:** Current `play_next` / `add_*` always `_send_message(interaction, ...)` and resolve voice via `interaction.guild.voice_client`. Web has no Interaction.

- [ ] **Step 1: Write failing test for snapshot + silent ops**

```python
# tests/test_music_player_web.py
from music import MusicPlayer, WebUser


class FakeBot:
    loop = None


def test_web_user_mention():
    u = WebUser()
    assert "Web" in u.mention or u.mention == "Web UI"


def test_snapshot_empty():
    p = MusicPlayer(FakeBot())
    snap = p.snapshot()
    assert snap["current"] is None
    assert snap["queue"] == []
    assert snap["is_playing"] is False
    assert 0 <= snap["volume"] <= 100
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_music_player_web.py -v
```

- [ ] **Step 3: Implement WebUser + snapshot + silent messaging**

In `music.py`:

```python
class WebUser:
    """Pseudo-user for web UI queue attribution."""
    def __init__(self, name: str = "Web UI"):
        self.id = 0
        self.name = name
        self.display_name = name

    @property
    def mention(self) -> str:
        return self.name
```

Update `_send_message`:

```python
    def _send_message(self, interaction, message, ephemeral=False):
        if interaction is None:
            return None  # web path: no Discord reply
        # ... existing logic ...
```

Update `_get_voice_client`:

```python
    def _get_voice_client(self, interaction):
        if self.voice_client is not None:
            return self.voice_client
        if interaction is None:
            return None
        return interaction.guild.voice_client
```

Add:

```python
    def set_voice_client(self, voice_client):
        self.voice_client = voice_client

    def snapshot(self):
        def song_dict(s):
            if not s:
                return None
            user = s.get("user")
            user_label = getattr(user, "name", None) or getattr(user, "mention", None) or str(user)
            return {
                "name": s.get("name"),
                "is_stream": bool(s.get("is_stream", False)),
                "user": user_label,
                "webpage_url": s.get("webpage_url") or "",
            }
        return {
            "current": song_dict(self.current),
            "queue": [song_dict(s) for s in list(self.queue)],
            "volume": self.get_volume(),
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
        }
```

Fix `play` after-callback so when interaction is None it still advances:

```python
        def _after(err):
            if err is not None:
                return
            fut = asyncio.run_coroutine_threadsafe(
                self.play_next(interaction),
                self.bot.loop,
            )
            # optional: fut.add_done_callback for logging

        self.voice_client.play(source, after=_after)
```

Ensure `play_next` with `interaction=None` still works when `self.voice_client` is set and queue non-empty; skip Discord messages.

Also update control methods (`skip`, `stop`, `pause`, `resume`, `set_volume`, `clear_queue`, `shuffle_queue`) so they work with `interaction=None` (already will if `_send_message` no-ops). For error conditions, raise or return status codes from **MusicService** (Task 4) rather than only messaging—player methods may return `None` and service checks state first.

- [ ] **Step 4: Run tests PASS**

```bash
pytest tests/test_music_player_web.py -v
```

- [ ] **Step 5: Manually sanity-check Discord path still imports**

```bash
python -c "from music import MusicPlayer, WebUser; print(WebUser().mention)"
```

- [ ] **Step 6: Commit**

```bash
git add music.py tests/test_music_player_web.py
git commit -m "refactor(music): support web playback without Discord Interaction"
```

---

### Task 4: MusicService (guild resolution + state + controls foundation)

**Files:**
- Create: `web/service.py`
- Create: `tests/test_web_service.py`
- Modify: `bot.py` / `web/app.py` to attach `MusicService` instance on `app.state.music_service`

**Interfaces:**
- Consumes: `bot`, `get_music_player(guild_id)`, `downloader`, `playlist_manager`, `Config`
- Produces:

```python
class ServiceError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        self.message = message
        self.code = code
        self.status = status

class MusicService:
    def __init__(self, bot, get_player, downloader, playlist_manager):
        ...

    def resolve_guild_id(self, guild_id: Optional[str] = None) -> int: ...
    def get_status(self, guild_id: Optional[str] = None) -> dict: ...
    def get_now(self, guild_id: Optional[str] = None) -> Optional[dict]: ...
    def get_queue(self, guild_id: Optional[str] = None) -> list: ...
    async def control(self, action: str, guild_id: Optional[str] = None) -> dict: ...
    async def set_volume(self, vol: int, guild_id: Optional[str] = None) -> dict: ...
    def list_voice_channels(self, guild_id: Optional[str] = None) -> list: ...
    async def join_voice(self, channel_id: str, guild_id: Optional[str] = None) -> dict: ...
    async def leave_voice(self, guild_id: Optional[str] = None) -> dict: ...
```

- [ ] **Step 1: Failing tests for guild resolution**

```python
# tests/test_web_service.py
import pytest
from web.service import MusicService, ServiceError


class G:
    def __init__(self, id, name="g"):
        self.id = id
        self.name = name
        self.voice_client = None
        self.voice_channels = []


class FakeBot:
    def __init__(self, guilds):
        self.guilds = guilds
        self.user = type("U", (), {"name": "bot"})()

    def get_guild(self, gid):
        for g in self.guilds:
            if g.id == gid:
                return g
        return None


def test_resolve_explicit_guild():
    bot = FakeBot([G(1), G(2)])
    svc = MusicService(bot, lambda i: None, None, None, default_guild_id="2")
    assert svc.resolve_guild_id("1") == 1


def test_resolve_default_env():
    bot = FakeBot([G(10), G(20)])
    svc = MusicService(bot, lambda i: None, None, None, default_guild_id="20")
    assert svc.resolve_guild_id(None) == 20


def test_resolve_sole_guild():
    bot = FakeBot([G(99)])
    svc = MusicService(bot, lambda i: None, None, None, default_guild_id=None)
    assert svc.resolve_guild_id(None) == 99


def test_resolve_ambiguous_raises():
    bot = FakeBot([G(1), G(2)])
    svc = MusicService(bot, lambda i: None, None, None, default_guild_id=None)
    with pytest.raises(ServiceError) as ei:
        svc.resolve_guild_id(None)
    assert ei.value.code == "GUILD_REQUIRED"
    assert ei.value.status == 400
```

- [ ] **Step 2: Run FAIL**

```bash
pytest tests/test_web_service.py -v
```

- [ ] **Step 3: Implement `web/service.py` (core)**

```python
from __future__ import annotations

from typing import Any, Callable, Optional

from music import WebUser


class ServiceError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class MusicService:
    def __init__(
        self,
        bot: Any,
        get_player: Callable[[int], Any],
        downloader: Any,
        playlist_manager: Any,
        default_guild_id: Optional[str] = None,
    ):
        self.bot = bot
        self.get_player = get_player
        self.downloader = downloader
        self.playlist_manager = playlist_manager
        self.default_guild_id = default_guild_id
        self._search_by_session: dict = {}  # session_key -> list[dict]

    def resolve_guild_id(self, guild_id: Optional[str] = None) -> int:
        if guild_id:
            try:
                return int(guild_id)
            except ValueError:
                raise ServiceError("Invalid guild_id", "INVALID_GUILD", 400)
        if self.default_guild_id:
            try:
                return int(self.default_guild_id)
            except ValueError:
                raise ServiceError("Invalid WEB_UI_GUILD_ID", "INVALID_GUILD", 400)
        guilds = list(getattr(self.bot, "guilds", []) or [])
        if len(guilds) == 1:
            return guilds[0].id
        raise ServiceError(
            "Set WEB_UI_GUILD_ID or pass guild_id (multiple guilds)",
            "GUILD_REQUIRED",
            400,
        )

    def _guild(self, guild_id: Optional[str] = None):
        gid = self.resolve_guild_id(guild_id)
        g = self.bot.get_guild(gid)
        if g is None:
            raise ServiceError("Guild not found", "GUILD_NOT_FOUND", 404)
        return g

    def _player(self, guild_id: Optional[str] = None):
        g = self._guild(guild_id)
        player = self.get_player(g.id)
        if g.voice_client:
            player.set_voice_client(g.voice_client)
        return player, g

    def get_status(self, guild_id: Optional[str] = None) -> dict:
        player, g = self._player(guild_id)
        vc = g.voice_client
        return {
            "online": self.bot.user is not None,
            "guild_id": str(g.id),
            "guild_name": g.name,
            "voice_channel": vc.channel.name if vc and vc.channel else None,
            "voice_channel_id": str(vc.channel.id) if vc and vc.channel else None,
            "volume": player.get_volume(),
            "is_playing": player.is_playing,
            "is_paused": player.is_paused,
        }

    def get_now(self, guild_id: Optional[str] = None):
        player, _ = self._player(guild_id)
        return player.snapshot()["current"]

    def get_queue(self, guild_id: Optional[str] = None) -> list:
        player, _ = self._player(guild_id)
        return player.snapshot()["queue"]

    def state_snapshot(self, guild_id: Optional[str] = None) -> dict:
        return {
            "status": self.get_status(guild_id),
            "now": self.get_now(guild_id),
            "queue": self.get_queue(guild_id),
        }

    async def control(self, action: str, guild_id: Optional[str] = None) -> dict:
        player, _ = self._player(guild_id)
        action = action.lower()
        if action == "pause":
            if not player.is_playing or player.is_paused:
                raise ServiceError("Nothing to pause", "INVALID_STATE", 409)
            await player.pause(None)
        elif action == "resume":
            if not player.is_paused:
                raise ServiceError("Not paused", "INVALID_STATE", 409)
            await player.resume(None)
        elif action == "skip":
            if not player.is_playing:
                raise ServiceError("Nothing playing", "INVALID_STATE", 409)
            await player.skip(None)
        elif action == "stop":
            await player.stop(None)
        elif action == "clear":
            await player.clear_queue(None)
        elif action == "shuffle":
            if len(player.queue) < 2:
                raise ServiceError("Need at least 2 songs", "INVALID_STATE", 409)
            await player.shuffle_queue(None)
        else:
            raise ServiceError("Unknown action", "UNKNOWN_ACTION", 400)
        return self.state_snapshot(guild_id)

    async def set_volume(self, vol: int, guild_id: Optional[str] = None) -> dict:
        if vol < 0 or vol > 100:
            raise ServiceError("vol must be 0-100", "INVALID_VOLUME", 400)
        player, _ = self._player(guild_id)
        await player.set_volume(None, vol / 100.0)
        return {"volume": player.get_volume()}

    def list_voice_channels(self, guild_id: Optional[str] = None) -> list:
        g = self._guild(guild_id)
        out = []
        for ch in g.voice_channels:
            out.append({"id": str(ch.id), "name": ch.name})
        return out

    async def join_voice(self, channel_id: str, guild_id: Optional[str] = None) -> dict:
        g = self._guild(guild_id)
        ch = g.get_channel(int(channel_id))
        if ch is None:
            # try voice channel lookup
            ch = next((c for c in g.voice_channels if str(c.id) == str(channel_id)), None)
        if ch is None:
            raise ServiceError("Voice channel not found", "CHANNEL_NOT_FOUND", 404)
        if g.voice_client is None:
            vc = await ch.connect()
        else:
            await g.voice_client.move_to(ch)
            vc = g.voice_client
        player = self.get_player(g.id)
        player.set_voice_client(vc)
        return self.get_status(str(g.id))

    async def leave_voice(self, guild_id: Optional[str] = None) -> dict:
        g = self._guild(guild_id)
        if g.voice_client is None:
            raise ServiceError("Not in a voice channel", "NOT_CONNECTED", 409)
        await g.voice_client.disconnect()
        player = self.get_player(g.id)
        player.cleanup()
        return {"ok": True}
```

Wire in bot when creating app:

```python
from web.service import MusicService
svc = MusicService(bot, get_music_player, downloader, playlist_manager, Config.WEB_UI_GUILD_ID)
app.state.music_service = svc
```

- [ ] **Step 4: Tests PASS**

```bash
pytest tests/test_web_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add web/service.py tests/test_web_service.py bot.py
git commit -m "feat(web): MusicService guild resolution and playback controls"
```

---

### Task 5: REST API routes (status, control, voice, auth-protected)

**Files:**
- Create: `web/routes/__init__.py`
- Create: `web/routes/api.py`
- Modify: `web/app.py` — `include_router` **before** static mount
- Create: `tests/test_web_api.py`

**Interfaces:**
- Consumes: `require_auth`, `app.state.music_service`
- Produces routes as in spec table (subset this task: status, now, queue, control, volume, channels, voice)

Helper for ServiceError:

```python
def raise_service(e: ServiceError):
    raise HTTPException(status_code=e.status, detail={"error": e.message, "code": e.code})
```

- [ ] **Step 1: Implement `web/routes/api.py`**

```python
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from web.auth import require_auth
from web.service import ServiceError

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def svc(request: Request):
    s = request.app.state.music_service
    if s is None:
        raise HTTPException(503, detail={"error": "Service unavailable", "code": "NO_SERVICE"})
    return s


def handle(e: ServiceError):
    raise HTTPException(status_code=e.status, detail={"error": e.message, "code": e.code})


@router.get("/status")
async def status(request: Request, guild_id: Optional[str] = None):
    try:
        return svc(request).get_status(guild_id)
    except ServiceError as e:
        handle(e)


@router.get("/now")
async def now(request: Request, guild_id: Optional[str] = None):
    try:
        return {"now": svc(request).get_now(guild_id)}
    except ServiceError as e:
        handle(e)


@router.get("/queue")
async def queue(request: Request, guild_id: Optional[str] = None):
    try:
        return {"queue": svc(request).get_queue(guild_id)}
    except ServiceError as e:
        handle(e)


@router.post("/control/{action}")
async def control(action: str, request: Request, guild_id: Optional[str] = None):
    try:
        return await svc(request).control(action, guild_id)
    except ServiceError as e:
        handle(e)


class VolumeBody(BaseModel):
    vol: int = Field(ge=0, le=100)
    guild_id: Optional[str] = None


@router.post("/volume")
async def volume(body: VolumeBody, request: Request):
    try:
        return await svc(request).set_volume(body.vol, body.guild_id)
    except ServiceError as e:
        handle(e)


@router.get("/channels")
async def channels(request: Request, guild_id: Optional[str] = None):
    try:
        return {"channels": svc(request).list_voice_channels(guild_id)}
    except ServiceError as e:
        handle(e)


class JoinBody(BaseModel):
    channel_id: str
    guild_id: Optional[str] = None


@router.post("/voice/join")
async def voice_join(body: JoinBody, request: Request):
    try:
        return await svc(request).join_voice(body.channel_id, body.guild_id)
    except ServiceError as e:
        handle(e)


@router.post("/voice/leave")
async def voice_leave(request: Request, guild_id: Optional[str] = None):
    try:
        return await svc(request).leave_voice(guild_id)
    except ServiceError as e:
        handle(e)
```

- [ ] **Step 2: Include router in `create_app` before static**

```python
    if full_ui:
        from web.routes.api import router as api_router
        app.include_router(api_router)
        # auth login routes already registered without require_auth
        if STATIC_DIR.is_dir():
            app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
```

Ensure login routes remain **outside** the protected router (already on app directly).

- [ ] **Step 3: API smoke test**

```python
# tests/test_web_api.py
from fastapi.testclient import TestClient
from web.app import create_app
from web.auth import create_session_secret
from web.service import MusicService


class G:
    def __init__(self, id):
        self.id = id
        self.name = "Test"
        self.voice_client = None
        self.voice_channels = []

    def get_channel(self, cid):
        return None


class FakeBot:
    def __init__(self):
        self.guilds = [G(1)]
        self.user = type("U", (), {"name": "b"})()

    def get_guild(self, gid):
        return self.guilds[0] if gid == 1 else None


class FakePlayer:
    def __init__(self):
        self.volume = 0.5
        self.is_playing = False
        self.is_paused = False
        self.current = None
        self.queue = type("D", (), {"__len__": lambda s: 0})()
        self.voice_client = None

    def set_voice_client(self, vc):
        self.voice_client = vc

    def get_volume(self):
        return 50

    def snapshot(self):
        return {
            "current": None,
            "queue": [],
            "volume": 50,
            "is_playing": False,
            "is_paused": False,
        }

    def cleanup(self):
        pass


def test_status_requires_auth_and_works_with_bearer():
    bot = FakeBot()
    player = FakePlayer()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: player, None, None, "1")
    client = TestClient(app)
    assert client.get("/api/status").status_code == 401
    r = client.get("/api/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["guild_name"] == "Test"
```

- [ ] **Step 4: Run PASS**

```bash
pytest tests/test_web_api.py tests/test_web_auth.py -v
```

- [ ] **Step 5: Commit**

```bash
git add web/routes web/app.py tests/test_web_api.py
git commit -m "feat(web): REST status, control, and voice endpoints"
```

---

### Task 6: Play, search, library, playlists on MusicService + API

**Files:**
- Modify: `web/service.py`
- Modify: `web/routes/api.py`
- Modify: `tests/test_web_api.py` (optional extra cases)
- May read: `downloader.py` (`search_youtube`, `get_stream_url`, `download_and_save`), `playlist.py` (load/save methods)

**Interfaces — add to MusicService:**

```python
async def play(self, query: str, download: bool = False, guild_id: Optional[str] = None) -> dict: ...
async def search(self, query: str, session_key: str, guild_id: Optional[str] = None) -> list: ...
async def search_play(self, index: int, session_key: str, guild_id: Optional[str] = None) -> dict: ...
def list_library(self) -> list: ...
async def library_play(self, name: str, guild_id: Optional[str] = None) -> dict: ...
def list_playlists(self) -> list: ...
async def create_playlist(self, name: str) -> dict: ...
async def delete_playlist(self, name: str) -> dict: ...
async def playlist_add(self, name: str, song: str) -> dict: ...
async def playlist_remove(self, name: str, song: str) -> dict: ...
async def playlist_play(self, name: str, guild_id: Optional[str] = None) -> dict: ...
```

- [ ] **Step 1: Implement play/search on service**

Logic mirror `bot.py` `/play` and `/search`:

```python
    async def play(self, query: str, download: bool = False, guild_id: Optional[str] = None) -> dict:
        player, g = self._player(guild_id)
        if g.voice_client is None:
            raise ServiceError("Join a voice channel first", "VOICE_NOT_CONNECTED", 409)
        player.set_voice_client(g.voice_client)
        user = WebUser()
        q = (query or "").strip()
        if not q:
            raise ServiceError("query required", "INVALID_QUERY", 400)

        if q.startswith(("http://", "https://", "www.")):
            try:
                if download:
                    path = await self.downloader.download_and_save(q)
                    if not path:
                        raise ServiceError("Download failed", "DOWNLOAD_FAILED", 502)
                    await player.add_to_queue(None, path, user)
                else:
                    info = await self.downloader.get_stream_url(q)
                    if not info:
                        raise ServiceError("Stream failed", "STREAM_FAILED", 502)
                    await player.add_stream_to_queue(None, info, user)
            except ServiceError:
                raise
            except Exception as e:
                raise ServiceError(str(e), "PLAY_ERROR", 502)
        else:
            import os
            from config import Config
            file_path = os.path.join(Config.MUSIC_DIR, q)
            if not os.path.exists(file_path):
                for ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
                    test = file_path + ext
                    if os.path.exists(test):
                        file_path = test
                        break
                else:
                    raise ServiceError("File not found; use search for YouTube", "NOT_FOUND", 404)
            await player.add_to_queue(None, file_path, user)
        return self.state_snapshot(str(g.id))

    async def search(self, query: str, session_key: str, guild_id: Optional[str] = None) -> list:
        try:
            results = await self.downloader.search_youtube(query, max_results=5)
        except Exception as e:
            raise ServiceError(str(e), "SEARCH_FAILED", 502)
        results = results or []
        # normalize to {title, url, duration, ...}
        self._search_by_session[session_key] = results
        return results

    async def search_play(self, index: int, session_key: str, guild_id: Optional[str] = None) -> dict:
        results = self._search_by_session.get(session_key) or []
        if index < 0 or index >= len(results):
            raise ServiceError("Invalid search index", "INVALID_INDEX", 400)
        item = results[index]
        url = item.get("url") or item.get("webpage_url")
        if not url:
            raise ServiceError("Result has no URL", "INVALID_RESULT", 400)
        return await self.play(url, download=False, guild_id=guild_id)
```

Session key: from cookie value hash or `request.state` — in routes, use `eca_session` cookie string or `"bearer"` + constant for Bearer clients:

```python
session_key = eca_session or (authorization or "anon")
```

- [ ] **Step 2: Library**

```python
    def list_library(self) -> list:
        import os
        from config import Config
        root = Config.MUSIC_DIR
        if not os.path.isdir(root):
            return []
        files = []
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name.lower().endswith((".mp3", ".wav", ".ogg", ".m4a", ".flac")):
                files.append({"name": name, "size": os.path.getsize(path)})
        return files

    async def library_play(self, name: str, guild_id: Optional[str] = None) -> dict:
        import os
        from config import Config
        base = os.path.basename(name)
        if base != name or ".." in name or "/" in name or "\\" in name:
            raise ServiceError("Invalid file name", "INVALID_PATH", 400)
        path = os.path.join(Config.MUSIC_DIR, base)
        if not os.path.isfile(path):
            raise ServiceError("File not found", "NOT_FOUND", 404)
        return await self.play(base, download=False, guild_id=guild_id)
```

- [ ] **Step 3: Playlists via PlaylistManager internals**

Prefer calling `_load_playlist` / `_save_playlist` / public methods. If public methods require interaction, add thin web-friendly methods on `PlaylistManager` or use private load/save from service:

```python
    def list_playlists(self) -> list:
        import os
        from config import Config
        out = []
        for fn in os.listdir(Config.PLAYLISTS_DIR):
            if fn.endswith(".json"):
                data = self.playlist_manager._load_playlist(fn[:-5])
                if data:
                    out.append({"name": data.get("name", fn[:-5]), "count": len(data.get("songs", []))})
        return out

    def create_playlist(self, name: str) -> dict:
        path = self.playlist_manager._get_playlist_path(name)
        import os
        if os.path.exists(path):
            raise ServiceError("Playlist exists", "EXISTS", 409)
        data = {"name": name, "owner": "web", "editors": [], "songs": []}
        if not self.playlist_manager._save_playlist(name, data):
            raise ServiceError("Save failed", "SAVE_FAILED", 500)
        return {"name": name, "songs": []}

    def delete_playlist(self, name: str) -> dict:
        import os
        path = self.playlist_manager._get_playlist_path(name)
        if not os.path.exists(path):
            raise ServiceError("Not found", "NOT_FOUND", 404)
        os.remove(path)
        return {"ok": True}

    def playlist_add(self, name: str, song: str) -> dict:
        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)
        data.setdefault("songs", []).append(song)
        self.playlist_manager._save_playlist(name, data)
        return data

    def playlist_remove(self, name: str, song: str) -> dict:
        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)
        songs = data.get("songs", [])
        data["songs"] = [s for s in songs if s != song]
        # if not removed by exact match, try remove first match containing
        self.playlist_manager._save_playlist(name, data)
        return data

    async def playlist_play(self, name: str, guild_id: Optional[str] = None) -> dict:
        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)
        songs = data.get("songs") or []
        if not songs:
            raise ServiceError("Playlist empty", "EMPTY", 409)
        last = None
        for song in songs:
            last = await self.play(song, download=False, guild_id=guild_id)
        return last or self.state_snapshot(guild_id)
```

- [ ] **Step 4: Add routes**

```python
class PlayBody(BaseModel):
    query: str
    download: bool = False
    guild_id: Optional[str] = None

class SearchBody(BaseModel):
    query: str
    guild_id: Optional[str] = None

class SearchPlayBody(BaseModel):
    index: int
    guild_id: Optional[str] = None

class NameBody(BaseModel):
    name: str

class SongBody(BaseModel):
    song: str

class LibraryPlayBody(BaseModel):
    name: str
    guild_id: Optional[str] = None


@router.post("/play")
async def play(body: PlayBody, request: Request):
    try:
        return await svc(request).play(body.query, body.download, body.guild_id)
    except ServiceError as e:
        handle(e)

@router.post("/search")
async def search(body: SearchBody, request: Request, eca_session: Optional[str] = Cookie(default=None, alias="eca_session"),
                 authorization: Optional[str] = Header(default=None)):
    key = eca_session or authorization or "default"
    try:
        results = await svc(request).search(body.query, key, body.guild_id)
        return {"results": results}
    except ServiceError as e:
        handle(e)

@router.post("/search/play")
async def search_play(body: SearchPlayBody, request: Request, eca_session: Optional[str] = Cookie(default=None, alias="eca_session"),
                      authorization: Optional[str] = Header(default=None)):
    key = eca_session or authorization or "default"
    try:
        return await svc(request).search_play(body.index, key, body.guild_id)
    except ServiceError as e:
        handle(e)

@router.get("/library")
async def library(request: Request):
    return {"files": svc(request).list_library()}

@router.post("/library/play")
async def library_play(body: LibraryPlayBody, request: Request):
    try:
        return await svc(request).library_play(body.name, body.guild_id)
    except ServiceError as e:
        handle(e)

@router.get("/playlists")
async def playlists(request: Request):
    return {"playlists": svc(request).list_playlists()}

@router.post("/playlists")
async def playlists_create(body: NameBody, request: Request):
    try:
        return svc(request).create_playlist(body.name)
    except ServiceError as e:
        handle(e)

@router.delete("/playlists/{name}")
async def playlists_delete(name: str, request: Request):
    try:
        return svc(request).delete_playlist(name)
    except ServiceError as e:
        handle(e)

@router.post("/playlists/{name}/add")
async def playlists_add(name: str, body: SongBody, request: Request):
    try:
        return svc(request).playlist_add(name, body.song)
    except ServiceError as e:
        handle(e)

@router.post("/playlists/{name}/remove")
async def playlists_remove(name: str, body: SongBody, request: Request):
    try:
        return svc(request).playlist_remove(name, body.song)
    except ServiceError as e:
        handle(e)

@router.post("/playlists/{name}/play")
async def playlists_play(name: str, request: Request, guild_id: Optional[str] = None):
    try:
        return await svc(request).playlist_play(name, guild_id)
    except ServiceError as e:
        handle(e)
```

- [ ] **Step 5: Run full unit suite**

```bash
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add web/service.py web/routes/api.py tests/
git commit -m "feat(web): play, search, library, and playlist API"
```

---

### Task 7: WebSocket state stream

**Files:**
- Create: `web/routes/ws.py`
- Modify: `web/app.py`

**Interfaces:**
- `WS /ws/state` — auth via cookie or `?token=`
- Push `state_snapshot()` every 1.5s until disconnect

- [ ] **Step 1: Implement ws router**

```python
# web/routes/ws.py
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from web.auth import tokens_match, verify_session, COOKIE_NAME

router = APIRouter()


@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket, token: str | None = Query(default=None)):
    await websocket.accept()
    app = websocket.app
    web_token = app.state.web_token
    secret = app.state.session_secret
    ok = False
    if token and tokens_match(web_token or "", token):
        ok = True
    else:
        cookie = websocket.cookies.get(COOKIE_NAME)
        if cookie and secret and verify_session(secret, cookie):
            ok = True
    if not ok:
        await websocket.close(code=4401)
        return
    try:
        while True:
            svc = app.state.music_service
            if svc is None:
                await websocket.send_json({"error": "no service"})
            else:
                try:
                    await websocket.send_json(svc.state_snapshot())
                except Exception as e:
                    await websocket.send_json({"error": str(e)})
            await asyncio.sleep(1.5)
    except WebSocketDisconnect:
        return
```

For Python 3.8 compatibility use `Optional[str]` instead of `str | None`.

- [ ] **Step 2: Include in app before static**

```python
        from web.routes.ws import router as ws_router
        app.include_router(ws_router)
```

- [ ] **Step 3: Manual note** — TestClient WebSocket optional; skip automated if flaky.

- [ ] **Step 4: Commit**

```bash
git add web/routes/ws.py web/app.py
git commit -m "feat(web): WebSocket state snapshots"
```

---

### Task 8: Dark control panel UI (static)

**Files:**
- Replace: `web/static/index.html`
- Create: `web/static/css/app.css`
- Create: `web/static/js/app.js`

**UI requirements (from spec):**
- Login screen if unauthenticated (probe `GET /api/status` → 401)
- Top bar: online, voice, guild, logout
- Tabs: Player | Queue | Search | Playlists | Library
- Sticky bottom player bar: now playing, pause/resume, skip, stop, volume
- Colors: `#0d0d12`, `#1a1a24`, `#5865F2`
- Responsive single column
- WS to `/ws/state` with cookie; fallback poll every 2.5s

- [ ] **Step 1: HTML structure**

`index.html` skeleton:

```html
<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ECA_BOT</title>
  <link rel="stylesheet" href="/css/app.css" />
</head>
<body>
  <div id="login-view" class="view">
    <form id="login-form" class="card login-card">
      <h1>ECA_BOT</h1>
      <p>Web kontrol paneli</p>
      <input type="password" id="token" placeholder="WEB_UI_TOKEN" autocomplete="current-password" />
      <button type="submit">Giriş</button>
      <p id="login-error" class="error" hidden></p>
    </form>
  </div>

  <div id="app-view" class="view" hidden>
    <header class="topbar">
      <div class="brand">ECA_BOT</div>
      <div id="status-line" class="status-line">…</div>
      <button id="logout-btn" type="button">Çıkış</button>
    </header>
    <nav class="tabs">
      <button data-tab="player" class="active">Player</button>
      <button data-tab="queue">Kuyruk</button>
      <button data-tab="search">Ara / Çal</button>
      <button data-tab="playlists">Playlist</button>
      <button data-tab="library">Kütüphane</button>
    </nav>
    <main>
      <section id="tab-player" class="tab-panel">
        <div class="card">
          <h2>Ses kanalı</h2>
          <select id="channel-select"></select>
          <button id="join-btn">Katıl</button>
          <button id="leave-btn">Ayrıl</button>
        </div>
        <div class="card">
          <h2>Hızlı çal</h2>
          <input id="play-query" placeholder="URL veya dosya adı" />
          <label><input type="checkbox" id="play-download" /> İndir</label>
          <button id="play-btn">Çal</button>
        </div>
      </section>
      <section id="tab-queue" class="tab-panel" hidden>
        <div class="card"><ul id="queue-list"></ul></div>
      </section>
      <section id="tab-search" class="tab-panel" hidden>
        <div class="card">
          <input id="search-query" placeholder="YouTube ara" />
          <button id="search-btn">Ara</button>
          <ul id="search-results"></ul>
        </div>
      </section>
      <section id="tab-playlists" class="tab-panel" hidden>
        <div class="card">
          <input id="pl-name" placeholder="Yeni playlist adı" />
          <button id="pl-create">Oluştur</button>
          <ul id="pl-list"></ul>
        </div>
      </section>
      <section id="tab-library" class="tab-panel" hidden>
        <div class="card"><ul id="lib-list"></ul></div>
      </section>
    </main>
    <footer class="player-bar">
      <div id="np-title" class="np-title">Çalmıyor</div>
      <div class="controls">
        <button id="btn-pause">Pause</button>
        <button id="btn-resume">Resume</button>
        <button id="btn-skip">Skip</button>
        <button id="btn-stop">Stop</button>
        <button id="btn-shuffle">Shuffle</button>
        <button id="btn-clear">Clear</button>
        <input type="range" id="vol" min="0" max="100" value="50" />
      </div>
    </footer>
  </div>
  <div id="toast" class="toast" hidden></div>
  <script src="/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: CSS** — implement dark layout, sticky footer player, card tabs, mobile stack. Key rules:

```css
:root {
  --bg: #0d0d12;
  --card: #1a1a24;
  --text: #e8e8f0;
  --muted: #9a9ab0;
  --accent: #5865f2;
  --green: #1db954;
}
body { margin: 0; background: var(--bg); color: var(--text); font-family: system-ui, sans-serif; }
.player-bar {
  position: fixed; left: 0; right: 0; bottom: 0;
  background: var(--card); border-top: 1px solid #2a2a38;
  padding: 0.75rem 1rem; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;
}
main { padding: 1rem; padding-bottom: 6rem; }
.card { background: var(--card); border-radius: 12px; padding: 1rem; margin-bottom: 1rem; }
button { background: var(--accent); color: white; border: 0; border-radius: 8px; padding: 0.5rem 0.9rem; cursor: pointer; }
/* ... tabs, login centered, errors, toast ... */
```

- [ ] **Step 3: JS API client**

Core pattern:

```javascript
async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const msg = (data && data.detail && data.detail.error) || (data && data.error) || res.statusText;
    throw new Error(msg);
  }
  return data;
}
```

Note FastAPI `HTTPException(detail=dict)` returns `{"detail": {"error": "...", "code": "..."}}`.

- Login: `POST /api/auth/login` `{token}`
- On load: try `GET /api/status`; if 401 show login
- Wire all buttons to endpoints
- `connectWs()` → `new WebSocket((location.protocol==="https:"?"wss":"ws")+"://"+location.host+"/ws/state")`; on message update UI; on error start `setInterval(refresh, 2500)`
- Search results: buttons calling `POST /api/search/play` `{index: i}`

- [ ] **Step 4: Visual smoke** — open browser against running bot with `WEB_UI_TOKEN`; login; confirm layout.

- [ ] **Step 5: Commit**

```bash
git add web/static
git commit -m "feat(web): dark Spotify/Discord-style control panel UI"
```

---

### Task 9: Docs, env example, final verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md` (new section: Web kontrol paneli)
- Optionally: `TROUBLESHOOTING.md` one paragraph on 401 / guild required

- [ ] **Step 1: `.env.example` additions**

```env
# --- Web kontrol paneli ---
# WEB_UI_TOKEN=uzun-rastgele-gizli-token
# WEB_UI_GUILD_ID=123456789012345678
# WEB_UI_SESSION_SECRET=oturum-imza-gizlisi
# ENABLE_HEALTH_SERVER=1
# PORT=8080
```

- [ ] **Step 2: README section**

Document:
1. Set `WEB_UI_TOKEN`, optional `WEB_UI_GUILD_ID`
2. Open `http://localhost:8080/`
3. Login with token
4. Join voice → play
5. Security warning: strong token if public
6. Health-only mode without token still via `ENABLE_HEALTH_SERVER`

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 4: Manual checklist**

- [ ] `/health` without auth → `OK`
- [ ] Login wrong token → 401
- [ ] Login ok → panel
- [ ] Join channel, play URL, skip, pause, volume
- [ ] Search + pick result
- [ ] Playlist create/add/play
- [ ] Library list/play
- [ ] Logout → 401 on API
- [ ] Without `WEB_UI_TOKEN` + with `ENABLE_HEALTH_SERVER` → health only

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md TROUBLESHOOTING.md
git commit -m "docs: web control panel setup and security notes"
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Same process FastAPI | 1 |
| full / health / off modes | 1 |
| Token + session cookie + Bearer | 2 |
| Rate limit login | 2 |
| Guild resolution order | 4 |
| MusicService + no Interaction | 3–4 |
| REST table (status, play, search, control, voice, playlists, library) | 5–6 |
| WebSocket + polling fallback | 7–8 |
| Dark UI layout | 8 |
| Path traversal safe library | 6 |
| Error JSON codes | 5–6 (`detail` dict; UI parses) |
| Config/env/README | 1, 9 |
| Tests auth + guild + API smoke | 2, 4, 5 |
| Docker same port | 1 (no compose change required if PORT already used) |

**Note on error shape:** FastAPI wraps `HTTPException.detail` as `{"detail": {...}}`. UI and docs must use that; optional middleware to flatten is YAGNI unless desired in Task 5.

**Placeholder scan:** None intentional. Implementers must still adapt `playlist.py` field names if JSON schema differs slightly—read `_load_playlist` samples under `playlists/`.

**Python 3.8:** Avoid `str | None` and `list[str]` in runtime code if targeting 3.8; use `Optional[str]`, `List[str]` from `typing`.

---

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-07-13-web-control-panel.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session, batch with checkpoints  

Which approach?
