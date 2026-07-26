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


class ReorderingPlayer(FakePlayer):
    def __init__(self):
        super().__init__()
        self.queue = [
            {"queue_id": "first", "name": "First"},
            {"queue_id": "second", "name": "Second"},
        ]

    def snapshot(self):
        return {
            "current": None,
            "queue": list(self.queue),
            "volume": 50,
            "is_playing": False,
            "is_paused": False,
        }

    def reorder_queue(self, queue_ids):
        entries = {entry["queue_id"]: entry for entry in self.queue}
        if set(queue_ids) != set(entries) or len(queue_ids) != len(entries):
            raise ValueError("invalid queue order")
        self.queue = [entries[queue_id] for queue_id in queue_ids]


class FakePlaylistManager:
    def __init__(self, playlists):
        self.playlists = playlists
        self.save_calls = 0

    def _load_playlist(self, name):
        data = self.playlists.get(name)
        if data is None:
            return None
        return {**data, "songs": list(data.get("songs") or [])}

    def _save_playlist(self, name, data):
        self.save_calls += 1
        self.playlists[name] = {**data, "songs": list(data.get("songs") or [])}
        return True


@pytest.mark.asyncio
async def test_reorder_queue_returns_reversed_snapshot_ids():
    """Catches a reorder operation that does not return the updated queue."""
    g = G(1)
    player = ReorderingPlayer()
    svc = MusicService(FakeBot([g]), lambda _id: player, None, None, "1")

    result = await svc.reorder_queue(["second", "first"])

    assert [entry["queue_id"] for entry in result["queue"]] == ["second", "first"]


@pytest.mark.asyncio
async def test_playlist_import_skips_existing_and_duplicate_urls_in_source_order():
    """Catches imports that save duplicate URLs or reorder source entries."""
    manager = FakePlaylistManager({"mix": {"name": "mix", "songs": ["old"]}})
    downloader = MagicMock()
    downloader.get_youtube_playlist_urls = AsyncMock(
        return_value=["old", "new", "new", "other"]
    )
    svc = MusicService(FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, manager, "1")

    result = await svc.playlist_import_youtube("mix", "https://youtube.com/playlist?list=abc")

    assert result == {
        "name": "mix",
        "songs": ["old", "new", "other"],
        "count": 3,
        "added": 2,
        "skipped": 2,
    }
    assert manager.save_calls == 1


@pytest.mark.asyncio
async def test_playlist_import_rejects_non_http_urls_before_extraction():
    """Catches unsafe URL schemes reaching the metadata extractor."""
    manager = FakePlaylistManager({"mix": {"name": "mix", "songs": []}})
    downloader = MagicMock()
    svc = MusicService(FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, manager, "1")

    with pytest.raises(ServiceError) as error:
        await svc.playlist_import_youtube("mix", "file:///private/list.txt")

    assert error.value.code == "INVALID_URL"
    assert error.value.status == 400
    downloader.get_youtube_playlist_urls.assert_not_called()


@pytest.mark.asyncio
async def test_playlist_import_translates_extraction_failure():
    """Catches downloader errors leaking as unstructured server failures."""
    manager = FakePlaylistManager({"mix": {"name": "mix", "songs": []}})
    downloader = MagicMock()
    downloader.get_youtube_playlist_urls = AsyncMock(side_effect=RuntimeError("yt-dlp failed"))
    svc = MusicService(FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, manager, "1")

    with pytest.raises(ServiceError) as error:
        await svc.playlist_import_youtube("mix", "https://youtube.com/playlist?list=abc")

    assert error.value.code == "IMPORT_FAILED"
    assert error.value.status == 502


@pytest.mark.asyncio
async def test_playlist_import_requires_existing_playlist():
    """Catches an import that creates or mutates a missing playlist."""
    downloader = MagicMock()
    svc = MusicService(
        FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, FakePlaylistManager({}), "1"
    )

    with pytest.raises(ServiceError) as error:
        await svc.playlist_import_youtube("missing", "https://youtube.com/playlist?list=abc")

    assert error.value.code == "NOT_FOUND"
    assert error.value.status == 404


def test_flat_playlist_extractor_keeps_valid_urls_and_canonicalizes_ids(monkeypatch):
    """Catches metadata extraction that downloads tracks or drops ID-only entries."""
    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is False
            return {
                "entries": [
                    {"webpage_url": "https://example.com/watch?v=one"},
                    {"id": "two"},
                    {"title": "no URL or id"},
                    None,
                ]
            }

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))
    import downloader as downloader_module

    monkeypatch.setattr(downloader_module.yt_dlp, "YoutubeDL", FakeYDL)
    instance = downloader_module.MusicDownloader.__new__(downloader_module.MusicDownloader)
    instance.cookie_file = None

    urls = instance._get_youtube_playlist_urls_sync("https://youtube.com/playlist?list=abc")

    assert urls == ["https://example.com/watch?v=one", "https://www.youtube.com/watch?v=two"]
    assert captured["extract_flat"] is True
    assert captured["skip_download"] is True


@pytest.mark.asyncio
async def test_reorder_queue_translates_invalid_player_order():
    """Catches player validation errors escaping the service API contract."""
    svc = MusicService(FakeBot([G(1)]), lambda _id: ReorderingPlayer(), None, None, "1")

    with pytest.raises(ServiceError) as error:
        await svc.reorder_queue(["missing"])

    assert error.value.code == "INVALID_QUEUE_ORDER"
    assert error.value.status == 400


@pytest.mark.asyncio
async def test_playlist_import_rejects_malformed_bracketed_host():
    """Catches URL parser errors leaking instead of returning INVALID_URL."""
    manager = FakePlaylistManager({"mix": {"name": "mix", "songs": []}})
    downloader = MagicMock()
    svc = MusicService(FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, manager, "1")

    with pytest.raises(ServiceError) as error:
        await svc.playlist_import_youtube("mix", "http://[")

    assert error.value.code == "INVALID_URL"
    assert error.value.status == 400
    downloader.get_youtube_playlist_urls.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("source_urls", "skipped"), [([], 0), (["old", "old"], 2)])
async def test_playlist_import_empty_or_all_duplicate_source_does_not_save(
    source_urls, skipped
):
    """Catches no-op imports being treated as errors or persisted unnecessarily."""
    manager = FakePlaylistManager({"mix": {"name": "mix", "songs": ["old"]}})
    downloader = MagicMock()
    downloader.get_youtube_playlist_urls = AsyncMock(return_value=source_urls)
    svc = MusicService(FakeBot([G(1)]), lambda _id: FakePlayer(), downloader, manager, "1")

    result = await svc.playlist_import_youtube("mix", "https://youtube.com/playlist?list=abc")

    assert result == {
        "name": "mix",
        "songs": ["old"],
        "count": 1,
        "added": 0,
        "skipped": skipped,
    }
    assert manager.save_calls == 0
