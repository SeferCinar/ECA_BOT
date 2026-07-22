import os
from unittest.mock import MagicMock, AsyncMock

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


class FakePlayer:
    def __init__(self):
        self.voice_client = "stale"
        self.volume = 0.5
        self.is_playing = False
        self.is_paused = False
        self.current = None
        self.queue = []

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
        self.voice_client = None
        self.queue.clear()
        self.is_playing = False
        self.is_paused = False
        self.current = None

    async def add_to_queue(self, interaction, file_path, user):
        self.queue.append(file_path)
        return True


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


def test_player_syncs_voice_client_even_when_none():
    g = G(1)
    g.voice_client = None
    bot = FakeBot([g])
    player = FakePlayer()
    assert player.voice_client == "stale"
    svc = MusicService(bot, lambda i: player, None, None, default_guild_id="1")
    p, guild = svc._player(None)
    assert p is player
    assert player.voice_client is None
    assert guild is g


@pytest.mark.asyncio
async def test_leave_voice_cleanup_clears_vc():
    g = G(1)
    vc = AsyncMock()
    g.voice_client = vc
    bot = FakeBot([g])
    player = FakePlayer()
    player.voice_client = vc
    svc = MusicService(bot, lambda i: player, None, None, default_guild_id="1")
    result = await svc.leave_voice()
    assert result["ok"] is True
    vc.disconnect.assert_awaited_once()
    assert player.voice_client is None


def test_safe_local_music_path_rejects_traversal(tmp_path, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MUSIC_DIR", str(tmp_path))
    with pytest.raises(ServiceError) as ei:
        MusicService._safe_local_music_path("../etc/passwd")
    assert ei.value.code == "INVALID_PATH"

    with pytest.raises(ServiceError) as ei:
        MusicService._safe_local_music_path("..\\secret")
    assert ei.value.code == "INVALID_PATH"

    with pytest.raises(ServiceError) as ei:
        MusicService._safe_local_music_path("sub/dir/song.mp3")
    assert ei.value.code == "INVALID_PATH"


def test_safe_local_music_path_allows_basename(tmp_path, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MUSIC_DIR", str(tmp_path))
    song = tmp_path / "track.mp3"
    song.write_bytes(b"x")
    resolved = MusicService._safe_local_music_path("track.mp3")
    assert os.path.realpath(resolved) == os.path.realpath(str(song))


def test_safe_local_music_path_extension_fallback(tmp_path, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MUSIC_DIR", str(tmp_path))
    song = tmp_path / "jam.mp3"
    song.write_bytes(b"x")
    resolved = MusicService._safe_local_music_path("jam")
    assert os.path.basename(resolved) == "jam.mp3"


@pytest.mark.asyncio
async def test_play_rejects_path_traversal(tmp_path, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MUSIC_DIR", str(tmp_path))
    g = G(1)
    g.voice_client = MagicMock()
    bot = FakeBot([g])
    player = FakePlayer()
    svc = MusicService(bot, lambda i: player, None, None, default_guild_id="1")
    with pytest.raises(ServiceError) as ei:
        await svc.play("../etc/passwd")
    assert ei.value.code == "INVALID_PATH"
    assert player.queue == []


@pytest.mark.asyncio
async def test_play_local_enqueue_failure_raises(tmp_path, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MUSIC_DIR", str(tmp_path))
    song = tmp_path / "ok.mp3"
    song.write_bytes(b"x")
    g = G(1)
    g.voice_client = MagicMock()
    bot = FakeBot([g])
    player = FakePlayer()

    async def fail_add(interaction, file_path, user):
        return False

    player.add_to_queue = fail_add
    svc = MusicService(bot, lambda i: player, None, None, default_guild_id="1")
    with pytest.raises(ServiceError) as ei:
        await svc.play("ok.mp3")
    assert ei.value.code == "NOT_FOUND"
