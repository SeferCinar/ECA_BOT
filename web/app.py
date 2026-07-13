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
