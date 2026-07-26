from __future__ import annotations

from typing import Any, Callable, Optional

from music import WebUser  # noqa: F401 — used by later tasks / play path


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
        # Always sync (including None) so leave/disconnect cannot leave a stale VC
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
        ch = None
        if hasattr(g, "get_channel"):
            try:
                ch = g.get_channel(int(channel_id))
            except (TypeError, ValueError):
                ch = None
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
        player.cleanup()  # stops playback and sets voice_client = None
        return {"ok": True}

    @staticmethod
    def _safe_local_music_path(query: str) -> str:
        """Resolve local basename under MUSIC_DIR; reject path traversal."""
        import os
        from config import Config

        q = (query or "").strip()
        base = os.path.basename(q)
        if not q or base != q or ".." in q or "/" in q or "\\" in q:
            raise ServiceError("Invalid file name", "INVALID_PATH", 400)

        music_root = os.path.realpath(Config.MUSIC_DIR)
        file_path = os.path.join(Config.MUSIC_DIR, base)
        if not os.path.exists(file_path):
            for ext in [".mp3", ".wav", ".ogg", ".m4a", ".flac"]:
                test = file_path + ext
                if os.path.exists(test):
                    file_path = test
                    break
            else:
                raise ServiceError("File not found; use search for YouTube", "NOT_FOUND", 404)

        resolved = os.path.realpath(file_path)
        if resolved != music_root and not resolved.startswith(music_root + os.sep):
            raise ServiceError("Invalid file name", "INVALID_PATH", 400)
        if not os.path.isfile(resolved):
            raise ServiceError("File not found; use search for YouTube", "NOT_FOUND", 404)
        return resolved

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
                    ok = await player.add_to_queue(None, path, user)
                    if not ok:
                        raise ServiceError("File not found after download", "NOT_FOUND", 404)
                else:
                    info = await self.downloader.get_stream_url(q)
                    if not info:
                        raise ServiceError("Stream failed", "STREAM_FAILED", 502)
                    ok = await player.add_stream_to_queue(None, info, user)
                    if not ok:
                        raise ServiceError("Failed to enqueue stream", "PLAY_ERROR", 502)
            except ServiceError:
                raise
            except Exception as e:
                raise ServiceError(str(e), "PLAY_ERROR", 502)
        else:
            file_path = self._safe_local_music_path(q)
            ok = await player.add_to_queue(None, file_path, user)
            if not ok:
                raise ServiceError("File not found; use search for YouTube", "NOT_FOUND", 404)
        return self.state_snapshot(str(g.id))

    async def search(self, query: str, session_key: str, guild_id: Optional[str] = None) -> list:
        try:
            results = await self.downloader.search_youtube(query, max_results=5)
        except Exception as e:
            raise ServiceError(str(e), "SEARCH_FAILED", 502)
        results = results or []
        # Normalize / ensure url from id when extract_flat leaves url empty
        normalized = []
        for item in results:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            if not entry.get("url") and not entry.get("webpage_url") and entry.get("id"):
                entry["url"] = "https://www.youtube.com/watch?v={}".format(entry["id"])
            elif entry.get("url") and not str(entry["url"]).startswith(("http://", "https://", "www.")):
                # flat extract sometimes puts id-ish values in url
                if entry.get("id"):
                    entry["url"] = "https://www.youtube.com/watch?v={}".format(entry["id"])
            normalized.append(entry)
        self._search_by_session[session_key] = normalized
        return normalized

    async def search_play(self, index: int, session_key: str, guild_id: Optional[str] = None) -> dict:
        results = self._search_by_session.get(session_key) or []
        if index < 0 or index >= len(results):
            raise ServiceError("Invalid search index", "INVALID_INDEX", 400)
        item = results[index]
        url = item.get("url") or item.get("webpage_url")
        if not url and item.get("id"):
            url = "https://www.youtube.com/watch?v={}".format(item["id"])
        if not url:
            raise ServiceError("Result has no URL", "INVALID_RESULT", 400)
        return await self.play(url, download=False, guild_id=guild_id)

    def list_library(self) -> list:
        import os
        from config import Config

        root = Config.MUSIC_DIR
        if not os.path.isdir(root):
            return []
        files = []
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(path) and name.lower().endswith(
                (".mp3", ".wav", ".ogg", ".m4a", ".flac")
            ):
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

    def list_playlists(self) -> list:
        import os
        from config import Config

        root = Config.PLAYLISTS_DIR
        if not os.path.isdir(root):
            return []
        out = []
        for fn in os.listdir(root):
            if fn.endswith(".json"):
                data = self.playlist_manager._load_playlist(fn[:-5])
                if data:
                    out.append(
                        {
                            "name": data.get("name", fn[:-5]),
                            "count": len(data.get("songs", [])),
                        }
                    )
        return out

    def get_playlist(self, name: str) -> dict:
        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)
        return {
            "name": data.get("name", name),
            "songs": list(data.get("songs") or []),
            "count": len(data.get("songs") or []),
        }

    def create_playlist(self, name: str) -> dict:
        import os

        path = self.playlist_manager._get_playlist_path(name)
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

    async def reorder_queue(
        self, queue_ids: list[str], guild_id: Optional[str] = None
    ) -> dict:
        player, _ = self._player(guild_id)
        try:
            player.reorder_queue(queue_ids)
        except ValueError as error:
            raise ServiceError(str(error), "INVALID_QUEUE_ORDER", 400)
        return player.snapshot()

    async def playlist_import_youtube(self, name: str, url: str) -> dict:
        from urllib.parse import urlparse

        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)

        try:
            parsed = urlparse(url or "")
            valid_url = parsed.scheme in {"http", "https"} and parsed.hostname
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ServiceError("Invalid URL", "INVALID_URL", 400)

        try:
            source_urls = await self.downloader.get_youtube_playlist_urls(url)
        except Exception as error:
            raise ServiceError(str(error), "IMPORT_FAILED", 502)

        data = self.playlist_manager._load_playlist(name)
        if not data:
            raise ServiceError("Not found", "NOT_FOUND", 404)

        songs = list(data.get("songs") or [])
        seen = set(songs)
        added = 0
        skipped = 0
        for song in source_urls or []:
            if song in seen:
                skipped += 1
                continue
            songs.append(song)
            seen.add(song)
            added += 1

        data["songs"] = songs
        if added:
            if not self.playlist_manager._save_playlist(name, data):
                raise ServiceError("Save failed", "SAVE_FAILED", 500)
        return {
            "name": data.get("name", name),
            "songs": songs,
            "count": len(songs),
            "added": added,
            "skipped": skipped,
        }
