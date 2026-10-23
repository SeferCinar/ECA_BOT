from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from web.app import create_app
from web.auth import create_session_secret
from web.service import MusicService, ServiceError


class G:
    def __init__(self, id):
        self.id = id
        self.name = "Test"
        self.voice_client = None
        self.voice_channels = []

    def get_channel(self, cid):
        return None


class FakeBot:
    def __init__(self):
        self.guilds = [G(1)]
        self.user = type("U", (), {"name": "b"})()

    def get_guild(self, gid):
        return self.guilds[0] if gid == 1 else None


class FakePlayer:
    def __init__(self):
        self.volume = 0.5
        self.is_playing = False
        self.is_paused = False
        self.current = None
        self.queue = type("D", (), {"__len__": lambda s: 0})()
        self.voice_client = None

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
    def reorder_queue(self, queue_ids):
        if queue_ids:
            raise ValueError("Unexpected queue IDs")


    def cleanup(self):
        pass


def test_status_requires_auth_and_works_with_bearer():
    bot = FakeBot()
    player = FakePlayer()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: player, None, None, "1")
    client = TestClient(app)
    assert client.get("/api/status").status_code == 401
    r = client.get("/api/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["guild_name"] == "Test"


def test_library_list_and_path_traversal_rejected():
    bot = FakeBot()
    player = FakePlayer()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: player, None, None, "1")
    client = TestClient(app)
    headers = {"Authorization": "Bearer t"}

    r = client.get("/api/library", headers=headers)
    assert r.status_code == 200
    assert "files" in r.json()

    r = client.post(
        "/api/library/play",
        headers=headers,
        json={"name": "../etc/passwd"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PATH"


def test_playlist_crud_via_api(tmp_path, monkeypatch):
    from playlist import PlaylistManager
    from config import Config

    monkeypatch.setattr(Config, "PLAYLISTS_DIR", str(tmp_path))
    bot = FakeBot()
    player = FakePlayer()
    pm = PlaylistManager()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: player, None, pm, "1")
    client = TestClient(app)
    headers = {"Authorization": "Bearer t"}

    r = client.post("/api/playlists", headers=headers, json={"name": "webmix"})
    assert r.status_code == 200
    assert r.json()["name"] == "webmix"

    r = client.post("/api/playlists/webmix/add", headers=headers, json={"song": "a.mp3"})
    assert r.status_code == 200
    assert "a.mp3" in r.json()["songs"]

    r = client.get("/api/playlists/webmix", headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "webmix"
    assert "a.mp3" in r.json()["songs"]

    r = client.get("/api/playlists", headers=headers)
    assert r.status_code == 200
    assert any(p["name"] == "webmix" for p in r.json()["playlists"])

    r = client.post(
        "/api/playlists/webmix/remove", headers=headers, json={"song": "a.mp3"}
    )
    assert r.status_code == 200
    assert r.json()["songs"] == []

    r = client.delete("/api/playlists/webmix", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_queue_reorder_requires_auth_and_returns_snapshot():
    bot = FakeBot()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    client = TestClient(app)

    assert client.post("/api/queue/reorder", json={"queue_ids": []}).status_code == 401

    response = client.post(
        "/api/queue/reorder",
        headers={"Authorization": "Bearer t"},
        json={"queue_ids": []},
    )

    assert response.status_code == 200
    assert response.json()["queue"] == []


def test_playlist_import_endpoint_returns_added_count():
    bot = FakeBot()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    service.playlist_import_youtube = AsyncMock(
        return_value={
            "name": "mix",
            "songs": ["https://youtube.com/watch?v=x"],
            "count": 1,
            "added": 1,
            "skipped": 0,
        }
    )
    app.state.music_service = service
    client = TestClient(app)

    response = client.post(
        "/api/playlists/mix/import-youtube",
        headers={"Authorization": "Bearer t"},
        json={"url": "https://www.youtube.com/playlist?list=x"},
    )

    assert response.status_code == 200
    assert response.json()["added"] == 1


def test_playlist_import_service_error_preserves_status_and_code():
    bot = FakeBot()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    service.playlist_import_youtube = AsyncMock(
        side_effect=ServiceError("Import failed", "IMPORT_FAILED", 502)
    )
    app.state.music_service = service
    client = TestClient(app)

    response = client.post(
        "/api/playlists/mix/import-youtube",
        headers={"Authorization": "Bearer t"},
        json={"url": "https://www.youtube.com/playlist?list=x"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "IMPORT_FAILED"


def test_queue_remove_requires_auth_and_maps_missing_to_404():
    bot = FakeBot()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    app.state.music_service = service
    client = TestClient(app)

    assert client.delete("/api/queue/abc").status_code == 401

    service.remove_from_queue = AsyncMock(return_value={"queue": []})
    response = client.delete("/api/queue/abc", headers={"Authorization": "Bearer t"})
    assert response.status_code == 200
    assert response.json()["queue"] == []
    service.remove_from_queue.assert_awaited_once_with("abc", None)

    service.remove_from_queue = AsyncMock(
        side_effect=ServiceError("Song not in queue", "NOT_IN_QUEUE", 404)
    )
    response = client.delete("/api/queue/abc", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_IN_QUEUE"


def test_autoplay_endpoint_toggles_player():
    bot = FakeBot()
    player = FakePlayer()
    player.autoplay = False
    player.set_autoplay = lambda enabled: setattr(player, "autoplay", enabled)
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = MusicService(bot, lambda gid: player, None, None, "1")
    client = TestClient(app)

    assert client.post("/api/autoplay", json={"enabled": True}).status_code == 401

    response = client.post("/api/autoplay", headers={"Authorization": "Bearer t"}, json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["status"]["autoplay"] is True


def test_play_passes_requested_by_label():
    bot = FakeBot()
    app = create_app(bot=bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    service.play = AsyncMock(return_value={"queue": []})
    app.state.music_service = service
    client = TestClient(app)

    response = client.post(
        "/api/play",
        headers={"Authorization": "Bearer t"},
        json={"query": "https://music.youtube.com/watch?v=dQw4w9WgXcQ", "requested_by": "YTMDesktop"},
    )

    assert response.status_code == 200
    service.play.assert_awaited_once_with(
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ", False, None, requested_by="YTMDesktop"
    )


def test_static_files_require_revalidation():
    app = create_app(bot=FakeBot(), full_ui=True)
    client = TestClient(app)

    response = client.get("/js/app.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def _app_with(service):
    app = create_app(bot=service.bot, full_ui=True)
    app.state.web_token = "t"
    app.state.session_secret = create_session_secret("s")
    app.state.music_service = service
    return TestClient(app)


def test_queue_add_validates_video_ids():
    bot = FakeBot()
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")
    service.add_tracks = AsyncMock(return_value={"added": 1})
    client = _app_with(service)
    auth = {"Authorization": "Bearer t"}

    assert client.post("/api/queue/add", json={"tracks": [{"video_id": "BSTsnWoslP4"}]}).status_code == 401
    assert client.post("/api/queue/add", headers=auth, json={"tracks": [{"video_id": "bad id"}]}).status_code == 422
    assert client.post("/api/queue/add", headers=auth, json={"tracks": []}).status_code == 422
    bad_thumb = {"tracks": [{"video_id": "BSTsnWoslP4", "thumbnail": "javascript:alert(1)"}]}
    assert client.post("/api/queue/add", headers=auth, json=bad_thumb).status_code == 422

    response = client.post(
        "/api/queue/add",
        headers=auth,
        json={"tracks": [{"video_id": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artists": "Queen",
                          "duration": "5:55", "thumbnail": "https://lh3.googleusercontent.com/x"}],
              "requested_by": "YT Music"},
    )

    assert response.status_code == 200
    service.add_tracks.assert_awaited_once_with(
        [{"video_id": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artists": "Queen",
          "duration": "5:55", "thumbnail": "https://lh3.googleusercontent.com/x"}], "YT Music", None
    )


def test_ytm_search_endpoint_maps_service_errors():
    bot = FakeBot()
    service = MusicService(bot, lambda gid: FakePlayer(), None, None, "1")  # no ytm client
    client = _app_with(service)

    response = client.get("/api/ytm/search", params={"q": "queen"}, headers={"Authorization": "Bearer t"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "YTM_UNAVAILABLE"


def test_seek_loop_filter_routes():
    service = MusicService(FakeBot(), lambda gid: FakePlayer(), None, None, "1")
    service.seek = AsyncMock(return_value={"ok": "seek"})
    service.set_loop = AsyncMock(return_value={"ok": "loop"})
    service.set_filter = AsyncMock(return_value={"ok": "filter"})
    client = _app_with(service)
    auth = {"Authorization": "Bearer t"}

    assert client.post("/api/seek", json={"position": 10}).status_code == 401
    assert client.post("/api/seek", headers=auth, json={"position": -1}).status_code == 422
    assert client.post("/api/seek", headers=auth, json={"position": 90.5}).json() == {"ok": "seek"}
    service.seek.assert_awaited_once_with(90.5, None)

    assert client.post("/api/loop", headers=auth, json={"mode": "song"}).json() == {"ok": "loop"}
    service.set_loop.assert_awaited_once_with("song", None)

    assert client.post("/api/filter", headers=auth, json={"name": "8d"}).json() == {"ok": "filter"}
    service.set_filter.assert_awaited_once_with("8d", None)
