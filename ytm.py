"""YouTube Music verisi (arama, albüm, playlist, ana sayfa) — ytmusicapi ile, hesap girişi olmadan.

Tüm çıktılar web arayüzü ve tarayıcı eklentisi için sade dict'lere çevrilir.
Şarkılar: {video_id, title, artists, album, duration, thumbnail}
"""
import asyncio
import re

MAX_COLLECTION_TRACKS = 200
_REF_RE = re.compile(r"^[A-Za-z0-9_-]{2,100}$")


def _artists(item) -> str:
    return ", ".join(a["name"] for a in item.get("artists") or [] if a.get("name"))


def _thumbnail(item, min_width: int = 120) -> str:
    """Listeler için yeterince büyük en küçük kapak resmi."""
    thumbs = sorted(item.get("thumbnails") or [], key=lambda t: t.get("width") or 0)
    for thumb in thumbs:
        if (thumb.get("width") or 0) >= min_width:
            return thumb.get("url", "")
    return thumbs[-1].get("url", "") if thumbs else ""


def track(item, album_title=None, album_thumbnail=""):
    """ytmusicapi şarkı/video girdisi -> track dict (çalınamıyorsa None)."""
    if not item.get("videoId") or item.get("isAvailable") is False:
        return None
    album = item.get("album")
    if isinstance(album, dict):  # arama sonuçlarında dict, albüm şarkılarında düz metin
        album = album.get("name")
    return {
        "video_id": item["videoId"],
        "title": item.get("title") or "",
        "artists": _artists(item),
        "album": album or album_title or "",
        "duration": item.get("duration") or "",
        "thumbnail": _thumbnail(item) or album_thumbnail,
    }


def album_card(item):
    return {
        "kind": "album",
        "id": item.get("browseId"),
        "title": item.get("title") or "",
        "subtitle": " · ".join(x for x in (item.get("type"), _artists(item), item.get("year")) if x),
        "thumbnail": _thumbnail(item),
    }


def playlist_card(item):
    playlist_id = item.get("playlistId") or item.get("browseId") or ""
    author = item.get("author")
    if isinstance(author, list):
        author = _artists({"artists": author})
    return {
        "kind": "playlist",
        "id": playlist_id,
        "title": item.get("title") or "",
        "subtitle": " · ".join(x for x in (author, item.get("itemCount") or item.get("count")) if x),
        "thumbnail": _thumbnail(item),
    }


def song_card(item):
    t = track(item)
    return {"kind": "song", **t} if t else None


def home_card(item):
    if item.get("videoId"):
        return song_card(item)
    if item.get("playlistId") and not str(item.get("browseId", "")).startswith("MPRE"):
        return playlist_card(item)
    if str(item.get("browseId", "")).startswith("MPRE"):
        return album_card(item)
    return None  # sanatçı vb.: eklenecek bir şey yok


def validate_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not _REF_RE.match(ref):
        raise ValueError("invalid id")
    return ref


class YTMClient:
    """ytmusicapi.YTMusic sarmalayıcısı. language='tr' ytmusicapi'nin ayrıştırmasını bozuyor, o yüzden yalnızca konum."""

    def __init__(self, location: str = "TR", factory=None):
        self._location = location
        self._factory = factory
        self._api = None

    @property
    def api(self):
        if self._api is None:
            if self._factory is not None:
                self._api = self._factory()
            else:
                from ytmusicapi import YTMusic

                self._api = YTMusic(location=self._location)
        return self._api

    # ----- senkron (executor'da çalışır) -----

    def _search(self, query: str, kind: str, limit: int):
        filter_name = {"songs": "songs", "albums": "albums", "playlists": "playlists"}[kind]
        results = self.api.search(query, filter=filter_name, limit=limit)
        cards = {"songs": song_card, "albums": album_card, "playlists": playlist_card}[kind]
        return [c for c in (cards(r) for r in results) if c and (c["kind"] == "song" or c.get("id"))][:limit]

    def _album(self, browse_id: str):
        data = self.api.get_album(browse_id)
        thumb = _thumbnail(data)
        tracks = [t for t in (track(x, data.get("title"), thumb) for x in data.get("tracks") or []) if t]
        return {
            "kind": "album",
            "id": browse_id,
            "title": data.get("title") or "",
            "subtitle": " · ".join(x for x in (_artists(data), data.get("year")) if x),
            "thumbnail": thumb,
            "tracks": tracks[:MAX_COLLECTION_TRACKS],
        }

    def _playlist(self, playlist_id: str):
        data = self.api.get_playlist(playlist_id, limit=MAX_COLLECTION_TRACKS)
        tracks = [t for t in (track(x) for x in data.get("tracks") or []) if t]
        author = data.get("author") or {}
        return {
            "kind": "playlist",
            "id": playlist_id,
            "title": data.get("title") or "",
            "subtitle": author.get("name", "") if isinstance(author, dict) else str(author),
            "thumbnail": _thumbnail(data),
            "tracks": tracks[:MAX_COLLECTION_TRACKS],
        }

    def _collection(self, ref: str):
        ref = validate_ref(ref)
        if ref.startswith("MPRE"):
            return self._album(ref)
        return self._playlist(ref[2:] if ref.startswith("VL") else ref)

    def _home(self, limit: int):
        sections = []
        for section in self.api.get_home(limit=limit):
            items = [c for c in (home_card(x) for x in section.get("contents") or []) if c]
            if items:
                sections.append({"title": section.get("title") or "", "items": items})
        return sections

    # ----- async -----

    async def search(self, query: str, kind: str = "songs", limit: int = 20):
        return await asyncio.to_thread(self._search, query, kind, limit)

    async def collection(self, ref: str):
        return await asyncio.to_thread(self._collection, ref)

    async def home(self, limit: int = 6):
        return await asyncio.to_thread(self._home, limit)
