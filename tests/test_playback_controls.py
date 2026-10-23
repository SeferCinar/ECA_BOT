"""Seek, loop mode, audio filters and playback position (no real Discord voice / FFmpeg)."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

import music
from music import (
    AUDIO_FILTERS, MusicPlayer, WebUser, format_time, parse_seek, parse_time, song_thumbnail,
)


class FakeBot:
    loop = None


class Clock:
    """time.monotonic yerine elle ilerletilen saat."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = Clock()
    with patch("music.time.monotonic", c):
        yield c


@pytest.fixture(autouse=True)
def ffmpeg():
    with patch("discord.FFmpegPCMAudio") as ffmpeg, patch("discord.PCMVolumeTransformer"):
        yield ffmpeg


def song(name, stream_url=None, **extra):
    vid = (name * 11)[:11]
    return {
        "name": name, "user": WebUser(), "is_stream": True,
        "stream_url": stream_url or f"https://stream/{vid}",
        "webpage_url": f"https://www.youtube.com/watch?v={vid}", **extra,
    }


async def playing(*songs):
    """Kuyruğa şarkıları koyup ilkini çalmaya başlat."""
    player = MusicPlayer(FakeBot())
    vc = MagicMock()
    vc.is_playing.return_value = True
    vc.is_paused.return_value = False
    player.set_voice_client(vc)
    player.queue.extend(songs)
    await player.play_next(None)
    return player, vc


async def finish(player, seconds, clock):
    """Çalan şarkı seconds sonra kendiliğinden bitti (after-callback -> play_next)."""
    clock.now += seconds
    await player.play_next(None)


# ----- zaman yardımcıları -----

@pytest.mark.parametrize("seconds, text", [(0, "0:00"), (90, "1:30"), (3723, "1:02:03"), (59.9, "0:59"), (-5, "0:00")])
def test_format_time(seconds, text):
    assert format_time(seconds) == text


@pytest.mark.parametrize("text, seconds", [("90", 90), ("1:30", 90), (" 1:02:03 ", 3723), ("0:05", 5)])
def test_parse_time(text, seconds):
    assert parse_time(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "1:", ":30", "1:2:3:4", "-5", "1.5", None])
def test_parse_time_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_parse_seek_relative_and_absolute():
    assert parse_seek("1:30", 200) == 90
    assert parse_seek("+15", 100.5) == 115.5
    assert parse_seek("-1:00", 100) == 40
    assert parse_seek("-30", 10) == 0
    with pytest.raises(ValueError):
        parse_seek("+", 10)


def test_song_thumbnail_prefers_given_url_then_youtube_id():
    assert song_thumbnail({"thumbnail": "https://lh3.googleusercontent.com/a"}) == "https://lh3.googleusercontent.com/a"
    assert song_thumbnail({"webpage_url": "https://youtu.be/dQw4w9WgXcQ"}) == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert song_thumbnail({"thumbnail": "javascript:x", "file": "/music/a.mp3"}) is None


def test_stream_url_expiry_check():
    soon = f"https://rr1.googlevideo.com/videoplayback?expire={int(time.time()) + 60}&x=1"
    later = f"https://rr1.googlevideo.com/videoplayback?expire={int(time.time()) + 6 * 3600}"
    assert music._stream_url_expiring(soon) is True
    assert music._stream_url_expiring(later) is False
    assert music._stream_url_expiring("https://example.com/a.mp3") is False
    assert music._stream_url_expiring(None) is False


# ----- FFmpeg kaynağı -----

def test_make_source_adds_seek_and_filter(ffmpeg):
    player = MusicPlayer(FakeBot())
    player.filter = "nightcore"

    player._make_source(song("a"), 90)

    args, kwargs = ffmpeg.call_args
    assert args == ("https://stream/aaaaaaaaaaa",)
    assert kwargs["before_options"].startswith("-reconnect 1")
    assert kwargs["before_options"].endswith("-ss 90.00")
    assert kwargs["options"] == f"-vn -af {AUDIO_FILTERS['nightcore'][1]}"


def test_make_source_local_file_without_extras(ffmpeg):
    MusicPlayer(FakeBot())._make_source({"file": "/music/a.mp3", "is_stream": False})

    assert ffmpeg.call_args.args == ("/music/a.mp3",)
    assert ffmpeg.call_args.kwargs == {"before_options": None, "options": "-vn"}


def test_filter_chains_have_no_spaces():
    """discord.py splits options with shlex; a space would break the -af argument."""
    for _, chain, _ in AUDIO_FILTERS.values():
        assert " " not in chain


# ----- konum -----

@pytest.mark.asyncio
async def test_position_follows_pause_resume_and_speed(clock):
    player, _ = await playing(song("a"))
    clock.now += 10
    assert player.position() == 10

    await player.pause(None)
    clock.now += 60
    assert player.position() == 10

    await player.resume(None)
    clock.now += 5
    assert player.position() == 15

    player._start_clock(15)
    player.filter = "nightcore"  # 1.25x
    clock.now += 4
    assert player.position() == 20


@pytest.mark.asyncio
async def test_snapshot_reports_playback_details(clock):
    player, _ = await playing(song("a", duration=200, thumbnail="https://img/a.jpg"))
    player.set_loop("queue")
    player.filter = "8d"
    clock.now += 42

    snap = player.snapshot()

    assert snap["current"]["position"] == 42
    assert snap["current"]["duration"] == 200
    assert snap["current"]["thumbnail"] == "https://img/a.jpg"
    assert snap["current"]["speed"] == 1.0
    assert snap["loop"] == "queue"
    assert snap["filter"] == "8d"


def test_enqueue_tracks_keeps_ytm_duration_and_thumbnail():
    player = MusicPlayer(FakeBot())

    player.enqueue_tracks([
        {"video_id": "aaaaaaaaaaa", "title": "A", "duration": "3:45", "thumbnail": "https://img/a"},
        {"video_id": "bbbbbbbbbbb", "title": "B", "duration": "live?"},
    ], WebUser())

    assert [s["duration"] for s in player.queue] == [225, None]
    assert player.queue[0]["thumbnail"] == "https://img/a"


# ----- seek -----

@pytest.mark.asyncio
async def test_seek_swaps_source_without_advancing(clock, ffmpeg):
    player, vc = await playing(song("a", duration=200), song("b"))
    old_source = vc.source
    clock.now += 10

    assert await player.seek(None, 90) is True

    assert ffmpeg.call_args.kwargs["before_options"].endswith("-ss 90.00")
    assert vc.source is not old_source
    vc.stop.assert_not_called()
    vc.play.assert_called_once()  # sadece ilk şarkı başlarken
    assert player.current["name"] == "a"
    assert player.position() == 90


@pytest.mark.asyncio
async def test_seek_keeps_pause(clock):
    player, vc = await playing(song("a", duration=200))
    await player.pause(None)
    vc.pause.reset_mock()

    await player.seek(None, 30)

    vc.pause.assert_called_once()
    clock.now += 100
    assert player.position() == 30


@pytest.mark.asyncio
async def test_seek_rejects_past_end_and_idle(clock):
    player, vc = await playing(song("a", duration=200))
    source = vc.source
    player._send_message = AsyncMock()

    assert await player.seek("i", 200) is False
    assert vc.source is source
    player._send_message.assert_awaited_with("i", "❌ Şarkı 3:20 uzunluğunda!", ephemeral=True)

    idle = MusicPlayer(FakeBot())
    assert await idle.seek(None, 10) is False


@pytest.mark.asyncio
async def test_seek_gives_up_when_song_changed_while_ffmpeg_started(clock, ffmpeg):
    player, vc = await playing(song("a"), song("b"))
    source = vc.source

    async def song_ends_meanwhile(func, *args):
        await player.play_next(None)  # şarkı kendiliğinden bitti

    with patch("music.asyncio.to_thread", song_ends_meanwhile):
        assert await player._restart_at(30) is False

    assert player.current["name"] == "b"
    assert vc.source is source
    ffmpeg.return_value.cleanup.assert_called()


# ----- filtre -----

@pytest.mark.asyncio
async def test_filter_applies_mid_song_from_current_position(clock, ffmpeg):
    player, vc = await playing(song("a", duration=300))
    clock.now += 50

    await player.set_filter(None, "slowed")

    assert player.filter == "slowed"
    assert ffmpeg.call_args.kwargs["before_options"].endswith("-ss 50.00")
    assert ffmpeg.call_args.kwargs["options"].endswith(AUDIO_FILTERS["slowed"][1])
    vc.stop.assert_not_called()
    clock.now += 10
    assert player.position() == pytest.approx(58)  # 0.8x


@pytest.mark.asyncio
async def test_filter_off_and_unknown(clock):
    player, _ = await playing(song("a"))
    await player.set_filter(None, "bassboost")
    await player.set_filter(None, None)
    assert player.filter is None
    with pytest.raises(ValueError):
        await player.set_filter(None, "chipmunk")


# ----- döngü -----

@pytest.mark.asyncio
async def test_song_loop_replays_until_skipped(clock):
    a, b = song("a"), song("b")
    player, vc = await playing(a, b)
    player.set_loop("song")

    await finish(player, 200, clock)
    assert player.current is a
    assert list(player.queue) == [b]

    await player.skip(None)
    await player.play_next(None)  # vc.stop() sonrası after-callback
    assert player.current is b


@pytest.mark.asyncio
async def test_queue_loop_moves_finished_and_skipped_songs_to_the_end(clock):
    a, b, c = song("a"), song("b"), song("c")
    player, _ = await playing(a, b, c)
    player.set_loop("queue")

    await finish(player, 200, clock)  # a bitti
    assert player.current is b
    assert list(player.queue) == [c, a]

    await player.skip(None)
    clock.now += 1  # hemen geçildi: yine de döngüde kalmalı
    await player.play_next(None)
    assert player.current is c
    assert list(player.queue) == [a, b]


@pytest.mark.asyncio
async def test_loop_skips_song_that_failed_immediately(clock):
    """A broken stream ends at once; looping it would spin forever."""
    a, b = song("a"), song("b")
    player, _ = await playing(a, b)
    player.set_loop("song")

    await finish(player, 0.5, clock)

    assert player.current is b
    assert a not in player.queue


@pytest.mark.asyncio
async def test_queue_loop_refreshes_expiring_stream_url(clock):
    expiring = f"https://rr1.googlevideo.com/videoplayback?expire={int(time.time()) + 60}"
    a, b = song("a", stream_url=expiring), song("b")
    player, _ = await playing(a, b)
    player.set_loop("queue")

    await finish(player, 200, clock)

    assert player.queue[-1] is a
    assert a["stream_url"] is None  # çalma sırası gelince yenisi alınır


def test_cycle_loop_and_validation():
    player = MusicPlayer(FakeBot())
    assert [player.cycle_loop() for _ in range(3)] == ["song", "queue", "off"]
    with pytest.raises(ValueError):
        player.set_loop("forever")


@pytest.mark.asyncio
async def test_stop_ignores_loop(clock):
    player, _ = await playing(song("a"), song("b"))
    player.set_loop("queue")

    await player.stop(None)
    await player.play_next(None)  # stop'un tetiklediği after-callback

    assert player.current is None
    assert len(player.queue) == 0


# ----- diğer -----

@pytest.mark.asyncio
async def test_skip_while_paused_plays_next(clock):
    a, b = song("a"), song("b")
    player, vc = await playing(a, b)
    await player.pause(None)

    await player.skip(None)
    await player.play_next(None)  # vc.stop() sonrası after-callback

    assert player.current is b
    assert player.is_paused is False


@pytest.mark.asyncio
async def test_expired_interaction_does_not_break_playback():
    interaction = MagicMock()
    interaction.response.is_done.return_value = True
    interaction.followup.send = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Webhook"))
    player = MusicPlayer(FakeBot())

    assert await player._send_message(interaction, "hi") is None


@pytest.mark.asyncio
async def test_player_notifies_card_on_changes(clock):
    player, _ = await playing(song("a"), song("b"))
    player.card = MagicMock()

    await player.pause(None)
    await player.resume(None)
    player.set_loop("song")
    await player.set_volume(None, 0.3)
    await player.shuffle_queue(None)
    await player.stop(None)

    assert player.card.refresh.call_count >= 5
