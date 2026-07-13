from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
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
