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
        player.cleanup()
        return {"ok": True}
