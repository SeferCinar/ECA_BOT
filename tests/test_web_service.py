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
