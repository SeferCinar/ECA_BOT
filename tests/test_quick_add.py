"""Quick add: songs enter the queue instantly; the stream URL is resolved when their turn comes."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music import MusicPlayer, WebUser, video_id_from_url
from web.service import MusicService, ServiceError
import ytm


class FakeBot:
    loop = None


def tracks(*ids):
    return [{"video_id": i, "title": f"Title {i}", "artists": "Artist"} for i in ids]


def make_player(resolve=None):
    downloader = MagicMock()

    async def default_resolve(url):
        vid = video_id_from_url(url)
        return {"url": f"https://stream/{vid}", "title": vid, "webpage_url": url}

    downloader.get_stream_url = AsyncMock(side_effect=resolve or default_resolve)
    player = MusicPlayer(FakeBot(), downloader)
    player.set_voice_client(MagicMock())
    return player


@pytest.fixture(autouse=True)
def no_ffmpeg():
    with patch("discord.FFmpegPCMAudio") as ffmpeg, patch("discord.PCMVolumeTransformer"):
        yield ffmpeg


async def settle(player):
    if player._start_task is not None:
        await player._start_task
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_enqueue_is_instant_and_keeps_click_order():
    player = make_player()

    player.enqueue_tracks(tracks("aaaaaaaaaaa"), WebUser("YT Music"))
    player.start_if_idle()
    player.enqueue_tracks(tracks("bbbbbbbbbbb"), WebUser("YT Music"))
    player.start_if_idle()  # same tick: must not start a second play_next
    player.enqueue_tracks(tracks("ccccccccccc"), WebUser("YT Music"))
    player.start_if_idle()
    await settle(player)

    assert player.current["webpage_url"].endswith("aaaaaaaaaaa")
    assert player.current["stream_url"] == "https://stream/aaaaaaaaaaa"
    assert player.current["name"] == "Artist - Title aaaaaaaaaaa"
    assert [s["webpage_url"][-11:] for s in player.queue] == ["bbbbbbbbbbb", "ccccccccccc"]
    assert all(s["stream_url"] is None for s in player.queue)  # not resolved yet
    player.voice_client.play.assert_called_once()


@pytest.mark.asyncio
async def test_unresolvable_song_is_skipped(no_ffmpeg):
    async def resolve(url):
        if "broken" in url:
            raise Exception("Video unavailable")
        return {"url": "https://stream/ok", "title": "ok", "webpage_url": url}

    player = make_player(resolve)
    player.enqueue_tracks(tracks("broken00000", "okokokokoko"), WebUser())
    player.start_if_idle()
    await settle(player)

    assert player.current["webpage_url"].endswith("okokokokoko")
    no_ffmpeg.assert_called_once()
    assert no_ffmpeg.call_args.args[0] == "https://stream/ok"


@pytest.mark.asyncio
async def test_skip_while_resolving_moves_to_next_song():
    gate = asyncio.Event()

    async def resolve(url):
        if "slow" in url:
            await gate.wait()
        return {"url": f"https://stream/{video_id_from_url(url)}", "title": "t", "webpage_url": url}

    player = make_player(resolve)
    player.enqueue_tracks(tracks("slowslowslo", "nextnextnex"), WebUser())
    player.start_if_idle()
    await asyncio.sleep(0)  # first song is now resolving
    assert player.snapshot()["is_loading"] is True

    await player.skip(None)
    await asyncio.sleep(0.01)
    gate.set()  # the skipped song's lookup finishes late
    await settle(player)
    await asyncio.sleep(0.01)

    assert player.current["webpage_url"].endswith("nextnextnex")
    player.voice_client.play.assert_called_once()
    assert player.snapshot()["is_loading"] is False


@pytest.mark.asyncio
async def test_stop_while_resolving_plays_nothing():
    gate = asyncio.Event()

    async def resolve(url):
        await gate.wait()
        return {"url": "https://stream/x", "title": "t", "webpage_url": url}

    player = make_player(resolve)
    player.enqueue_tracks(tracks("aaaaaaaaaaa", "bbbbbbbbbbb"), WebUser())
    player.start_if_idle()
    await asyncio.sleep(0)

    await player.stop(None)
    gate.set()
    await settle(player)

    player.voice_client.play.assert_not_called()
    assert player.current is None
    assert len(player.queue) == 0


@pytest.mark.asyncio
async def test_pause_while_resolving_starts_paused():
    gate = asyncio.Event()

    async def resolve(url):
        await gate.wait()
        return {"url": "https://stream/x", "title": "t", "webpage_url": url}

    player = make_player(resolve)
    player.enqueue_tracks(tracks("aaaaaaaaaaa"), WebUser())
    player.start_if_idle()
    await asyncio.sleep(0)

    await player.pause(None)
    gate.set()
    await settle(player)

    player.voice_client.play.assert_called_once()
    player.voice_client.pause.assert_called()
    assert player.is_paused is True


# ---------- MusicService ----------

class G:
    def __init__(self, voice_client=None):
        self.id = 1
        self.name = "g"
        self.voice_client = voice_client
        self.voice_channels = []


class Bot:
    def __init__(self, guild):
        self.guilds = [guild]
        self.user = object()

    def get_guild(self, gid):
        return self.guilds[0]


@pytest.mark.asyncio
async def test_add_tracks_requires_voice_channel():
    svc = MusicService(Bot(G()), lambda _id: make_player(), None, None, "1")

    with pytest.raises(ServiceError) as exc:
        await svc.add_tracks(tracks("aaaaaaaaaaa"))
    assert exc.value.code == "VOICE_NOT_CONNECTED"


@pytest.mark.asyncio
async def test_add_collection_enqueues_all_tracks_with_label():
    player = make_player()
    fake_ytm = MagicMock()
    fake_ytm.collection = AsyncMock(return_value={
        "kind": "album", "title": "A Night At The Opera", "tracks": tracks("aaaaaaaaaaa", "bbbbbbbbbbb"),
    })
    svc = MusicService(Bot(G(MagicMock())), lambda _id: player, None, None, "1", ytm=fake_ytm)

    result = await svc.add_collection("MPREb_eEpQf8QskKl", requested_by="YT Music")
    await settle(player)

    assert result["added"] == 2
    assert result["collection"] == {"kind": "album", "title": "A Night At The Opera"}
    assert player.current["user"].name == "YT Music"
    assert len(player.queue) == 1


@pytest.mark.asyncio
async def test_ytm_errors_are_translated():
    fake_ytm = MagicMock()
    fake_ytm.collection = AsyncMock(side_effect=ValueError("invalid id"))
    fake_ytm.search = AsyncMock(side_effect=Exception("HTTP 429"))
    svc = MusicService(Bot(G(MagicMock())), lambda _id: make_player(), None, None, "1", ytm=fake_ytm)

    with pytest.raises(ServiceError) as exc:
        await svc.ytm_collection("bad id!")
    assert (exc.value.status, exc.value.code) == (400, "INVALID_ID")

    with pytest.raises(ServiceError) as exc:
        await svc.ytm_search("queen", "songs")
    assert (exc.value.status, exc.value.code) == (502, "YTM_FAILED")

    with pytest.raises(ServiceError) as exc:
        await svc.ytm_search("queen", "artists")
    assert exc.value.code == "INVALID_KIND"


# ---------- ytm.py normalization ----------

class FakeYTMusic:
    def search(self, query, filter, limit):
        return {
            "songs": [
                {"videoId": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artists": [{"name": "Queen"}],
                 "album": {"name": "A Night At The Opera"}, "duration": "5:55",
                 "thumbnails": [{"url": "small", "width": 60}, {"url": "medium", "width": 120}]},
                {"videoId": None, "title": "unavailable"},
            ],
            "albums": [{"browseId": "MPREb_eEpQf8QskKl", "title": "ANATO", "type": "Album",
                        "artists": [{"name": "Queen"}], "year": "1975", "thumbnails": []}],
            "playlists": [{"browseId": "VLPLexq5cxhVyKITAzYcI7dRChk6K2P0NfMw", "title": "rock", "author": "Kulak"}],
        }[filter]

    def get_album(self, browse_id):
        return {"title": "ANATO", "artists": [{"name": "Queen"}], "year": "1975",
                "thumbnails": [{"url": "cover", "width": 226}],
                "tracks": [{"videoId": "kqVpk0qxmfA", "title": "Death On Two Legs", "artists": [{"name": "Queen"}],
                            "album": "ANATO", "thumbnails": None},
                           {"videoId": "xxxxxxxxxxx", "title": "greyed out", "isAvailable": False}]}

    def get_playlist(self, playlist_id, limit):
        self.last_playlist_id = playlist_id
        return {"title": "rock", "author": {"name": "Kulak"}, "tracks": [
            {"videoId": "oLTjUGStpjg", "title": "Oje", "artists": [{"name": "Duman"}], "album": None}]}


@pytest.mark.asyncio
async def test_ytm_search_normalizes_and_drops_unplayable():
    client = ytm.YTMClient(factory=FakeYTMusic)

    songs = await client.search("q", "songs")
    albums = await client.search("q", "albums")

    assert songs == [{"kind": "song", "video_id": "BSTsnWoslP4", "title": "Bohemian Rhapsody", "artists": "Queen",
                      "album": "A Night At The Opera", "duration": "5:55", "thumbnail": "medium"}]
    assert albums[0]["id"] == "MPREb_eEpQf8QskKl"
    assert albums[0]["subtitle"] == "Album · Queen · 1975"


@pytest.mark.asyncio
async def test_ytm_collection_routes_albums_and_playlists():
    fake = FakeYTMusic()
    client = ytm.YTMClient(factory=lambda: fake)

    album = await client.collection("MPREb_eEpQf8QskKl")
    playlist = await client.collection("VLPLexq5cxhVyKITAzYcI7dRChk6K2P0NfMw")

    assert [t["video_id"] for t in album["tracks"]] == ["kqVpk0qxmfA"]
    assert album["tracks"][0]["thumbnail"] == "cover"  # falls back to the album cover
    assert fake.last_playlist_id == "PLexq5cxhVyKITAzYcI7dRChk6K2P0NfMw"  # VL prefix stripped
    assert playlist["tracks"][0]["artists"] == "Duman"
    with pytest.raises(ValueError):
        await client.collection("../etc/passwd")
