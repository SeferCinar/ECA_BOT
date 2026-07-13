from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).resolve().parent / "static"


class LoginBody(BaseModel):
    token: str


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

    if full_ui:
        from web.auth import (
            COOKIE_NAME,
            check_login_rate,
            record_login_failure,
            sign_session,
            tokens_match,
        )

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

        from web.routes.api import router as api_router

        app.include_router(api_router)
        # auth login routes already registered without require_auth
        if STATIC_DIR.is_dir():
            app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


async def start_web_server(app: FastAPI, host: str = "0.0.0.0", port: int = 8080):
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info", loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()
