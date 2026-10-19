"""Autoplay: when the queue runs out, continue with related songs (no real Discord/YouTube)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from music import MusicPlayer, WebUser, video_id_from_url


class FakeBot:
    loop = None


def watch(video_id):
    return f"https://www.youtube.com/watch?v={video_id}"


def stream_info(video_id):
    return {"url": f"https://stream/{video_id}", "title": f"Song {video_id}", "webpage_url": watch(video_id)}


def make_player(related, stream=None):
    downloader = MagicMock()
    downloader.get_related_videos = AsyncMock(return_value=[{"id": i, "title": i} for i in related])
    downloader.get_stream_url = AsyncMock(side_effect=stream or (lambda url: stream_info(video_id_from_url(url))))
    player = MusicPlayer(FakeBot(), downloader)
    player.set_voice_client(MagicMock())
    player.set_autoplay(True)
    return player, downloader


def finished_song(video_id="seed0000000", **extra):
    return {"name": "seed", "user": WebUser(), "is_stream": True, "webpage_url": watch(video_id), **extra}


@pytest.fixture(autouse=True)
def no_ffmpeg():
    with patch("discord.FFmpegPCMAudio"), patch("discord.PCMVolumeTransformer"):
        yield


@pytest.mark.parametrize("url, expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RDAMVMdQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=10", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("/app/music/song.mp3", None),
    ("", None),
    (None, None),
])
def test_video_id_from_url(url, expected):
    assert video_id_from_url(url) == expected


@pytest.mark.asyncio
async def test_queue_end_plays_first_unplayed_related_song():
    player, downloader = make_player(["played0000a", "fresh00000b", "fresh00000c"])
    player.played_ids.append("played0000a")
    player.current = finished_song()

    await player.play_next(None)

    downloader.get_related_videos.assert_awaited_once_with("seed0000000")
    assert player.current["webpage_url"] == watch("fresh00000b")
    assert player.current["autoplay"] is True
    assert player.current["user"].name == "Autoplay"
    assert player.is_playing is True
    player.voice_client.play.assert_called_once()


@pytest.mark.asyncio
async def test_disabled_autoplay_does_nothing():
    player, downloader = make_player(["fresh00000b"])
    player.set_autoplay(False)
    player.current = finished_song()

    await player.play_next(None)

    downloader.get_related_videos.assert_not_awaited()
    assert player.current is None
    assert player.is_playing is False


@pytest.mark.asyncio
async def test_after_stop_autoplay_does_not_start():
    """stop() clears current before the voice after-callback runs play_next."""
    player, downloader = make_player(["fresh00000b"])
    player.current = finished_song()
    player.is_playing = True

    await player.stop(None)
    await player.play_next(None)

    downloader.get_related_videos.assert_not_awaited()
    assert player.current is None


@pytest.mark.asyncio
async def test_stop_during_lookup_cancels_autoplay():
    player, _ = make_player(["fresh00000b"])

    async def slow_stream(url):
        await player.stop(None)  # user hits stop while the stream URL is being resolved
        return stream_info(video_id_from_url(url))

    player.downloader.get_stream_url = AsyncMock(side_effect=slow_stream)
    player.current = finished_song()

    await player.play_next(None)

    assert player.current is None
    assert len(player.queue) == 0
    assert player.is_playing is False


@pytest.mark.asyncio
async def test_user_song_added_during_lookup_wins():
    player, _ = make_player(["fresh00000b"])
    user_song = {"name": "user pick", "user": WebUser(), "is_stream": True, "stream_url": "x",
                 "webpage_url": watch("userpick000")}

    async def slow_stream(url):
        player.queue.append(user_song)
        await player.play_next(None)  # what add_stream_to_queue does while idle
        return stream_info(video_id_from_url(url))

    player.downloader.get_stream_url = AsyncMock(side_effect=slow_stream)
    player.current = finished_song()

    await player.play_next(None)

    assert player.current is user_song
    assert len(player.queue) == 0


@pytest.mark.asyncio
async def test_stream_failure_falls_back_to_next_candidate():
    def flaky(url):
        if "broken" in url:
            raise Exception("yt-dlp hatası")
        return stream_info(video_id_from_url(url))

    player, _ = make_player(["broken0000b", "fresh00000c"], stream=flaky)
    player.current = finished_song()

    await player.play_next(None)

    assert player.current["webpage_url"] == watch("fresh00000c")


@pytest.mark.asyncio
async def test_autoplay_song_reuses_pool_until_exhausted():
    player, downloader = make_player(["fresh00000b", "fresh00000c"])
    player.current = finished_song()

    await player.play_next(None)  # user seed -> fetch radio, play b
    await player.play_next(None)  # autoplay song b ended -> next from same radio

    downloader.get_related_videos.assert_awaited_once()
    assert player.current["webpage_url"] == watch("fresh00000c")


@pytest.mark.asyncio
async def test_new_user_seed_refreshes_radio():
    player, downloader = make_player(["fresh00000b", "fresh00000c"])
    player.current = finished_song()
    await player.play_next(None)

    player.current = finished_song("otherseed00")  # a user-requested song just ended
    await player.play_next(None)

    assert [c.args[0] for c in downloader.get_related_videos.await_args_list] == ["seed0000000", "otherseed00"]


@pytest.mark.asyncio
async def test_nothing_related_reports_empty_queue():
    player, _ = make_player([])
    player.current = finished_song()
    interaction = MagicMock()
    player._send_message = AsyncMock()

    await player.play_next(interaction)

    player._send_message.assert_awaited_once_with(interaction, "📭 Kuyruk boş!")


def test_snapshot_reports_autoplay():
    player = MusicPlayer(FakeBot())
    assert player.snapshot()["autoplay"] is False
    player.set_autoplay(True)
    assert player.snapshot()["autoplay"] is True


def test_related_videos_fall_back_to_youtube_mix_when_radio_empty(monkeypatch):
    from downloader import MusicDownloader

    downloader = MusicDownloader.__new__(MusicDownloader)  # skip cookie/node discovery
    calls = []

    def fake_entries(url, video_id, limit):
        calls.append(url)
        return [] if "music.youtube.com" in url else [{"id": "fresh00000b", "title": "b"}]

    monkeypatch.setattr(downloader, "_get_mix_entries_sync", fake_entries)

    assert downloader._get_related_videos_sync("seed0000000", 25) == [{"id": "fresh00000b", "title": "b"}]
    assert calls == [
        "https://music.youtube.com/watch?v=seed0000000&list=RDAMVMseed0000000",
        "https://www.youtube.com/watch?v=seed0000000&list=RDseed0000000",
    ]
