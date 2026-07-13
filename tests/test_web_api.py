from fastapi.testclient import TestClient
from web.app import create_app
from web.auth import create_session_secret
from web.service import MusicService


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
