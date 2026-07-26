from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
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


class QueueReorderBody(BaseModel):
    queue_ids: list[str]
    guild_id: Optional[str] = None


@router.post("/queue/reorder")
async def queue_reorder(body: QueueReorderBody, request: Request):
    try:
        return await svc(request).reorder_queue(body.queue_ids, body.guild_id)
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
async def search(
    body: SearchBody,
    request: Request,
    eca_session: Optional[str] = Cookie(default=None, alias="eca_session"),
    authorization: Optional[str] = Header(default=None),
):
    key = eca_session or authorization or "default"
    try:
        results = await svc(request).search(body.query, key, body.guild_id)
        return {"results": results}
    except ServiceError as e:
        handle(e)


@router.post("/search/play")
async def search_play(
    body: SearchPlayBody,
    request: Request,
    eca_session: Optional[str] = Cookie(default=None, alias="eca_session"),
    authorization: Optional[str] = Header(default=None),
):
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


class YoutubeImportBody(BaseModel):
    url: str


@router.post("/playlists/{name}/import-youtube")
async def playlists_import_youtube(
    name: str, body: YoutubeImportBody, request: Request
):
    try:
        return await svc(request).playlist_import_youtube(name, body.url)
    except ServiceError as e:
        handle(e)


@router.get("/playlists")
async def playlists(request: Request):
    return {"playlists": svc(request).list_playlists()}


@router.get("/playlists/{name}")
async def playlists_get(name: str, request: Request):
    try:
        return svc(request).get_playlist(name)
    except ServiceError as e:
        handle(e)


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
