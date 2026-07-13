import asyncio
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from web.auth import COOKIE_NAME, tokens_match, verify_session

router = APIRouter()


@router.websocket("/ws/state")
async def ws_state(websocket: WebSocket, token: Optional[str] = Query(default=None)):
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
