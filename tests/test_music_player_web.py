"""Lightweight tests for MusicPlayer web/interaction-optional path (no real Discord voice)."""
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from music import MusicPlayer, WebUser


class FakeBot:
    loop = None


def test_web_user_mention():
    u = WebUser()
    assert "Web" in u.mention or u.mention == "Web UI"


def test_web_user_custom_name():
    u = WebUser(name="Panel")
    assert u.name == "Panel"
    assert u.display_name == "Panel"
    assert u.id == 0
    assert u.mention == "Panel"


def test_snapshot_empty():
    p = MusicPlayer(FakeBot())
    snap = p.snapshot()
    assert snap["current"] is None
    assert snap["queue"] == []
    assert snap["is_playing"] is False
    assert snap["is_paused"] is False
    assert 0 <= snap["volume"] <= 100


def test_snapshot_with_queue():
    p = MusicPlayer(FakeBot())
    user = WebUser()
    p.queue.append({
        "file": "/tmp/a.mp3",
        "name": "a.mp3",
        "user": user,
        "is_stream": False,
        "webpage_url": "",
    })
    p.current = {
        "stream_url": "https://example.com/x",
        "name": "Now Playing",
        "user": user,
        "is_stream": True,
        "webpage_url": "https://youtube.com/watch?v=1",
    }
    p.is_playing = True
    p.volume = 0.75

    snap = p.snapshot()
    assert snap["current"]["name"] == "Now Playing"
    assert snap["current"]["is_stream"] is True
    assert snap["current"]["user"] == "Web UI"
    assert snap["current"]["webpage_url"] == "https://youtube.com/watch?v=1"
    assert len(snap["queue"]) == 1
    assert snap["queue"][0]["name"] == "a.mp3"
    assert snap["is_playing"] is True
    assert snap["volume"] == 75


def test_snapshot_queue_ids_distinguish_identical_queued_songs():
    """Queued duplicates need independently addressable IDs for web controls."""
    p = MusicPlayer(FakeBot())
    user = WebUser()
    for _ in range(2):
        p.queue.append({
            "file": "/tmp/duplicate.mp3",
            "name": "duplicate.mp3",
            "user": user,
            "is_stream": False,
        })

    queue_ids = [song["queue_id"] for song in p.snapshot()["queue"]]

    assert all(queue_ids)
    assert len(set(queue_ids)) == 2


def test_reorder_queue_reverses_pending_without_changing_current_song():
    """Reorder must apply solely to pending tracks, never the active track."""
    p = MusicPlayer(FakeBot())
    user = WebUser()
    p.current = {"name": "Current", "user": user, "is_stream": False}
    p.queue.extend([
        {"name": "First", "user": user, "is_stream": False},
        {"name": "Second", "user": user, "is_stream": False},
    ])
    original_current = p.current
    original_ids = [song["queue_id"] for song in p.snapshot()["queue"]]

    p.reorder_queue(list(reversed(original_ids)))

    assert p.current is original_current
    assert [song["name"] for song in p.snapshot()["queue"]] == ["Second", "First"]


def test_reorder_queue_invalid_ids_leave_pending_order_intact():
    """Invalid orders must be rejected before they mutate the pending queue."""
    p = MusicPlayer(FakeBot())
    user = WebUser()
    p.queue.extend([
        {"name": "First", "user": user, "is_stream": False},
        {"name": "Second", "user": user, "is_stream": False},
    ])
    original_names = [song["name"] for song in p.queue]
    queue_ids = [song["queue_id"] for song in p.snapshot()["queue"]]
    invalid_orders = [
        ["stale-id", queue_ids[1]],
        [queue_ids[0], queue_ids[0]],
        [queue_ids[0]],
    ]

    for invalid_order in invalid_orders:
        with pytest.raises(ValueError, match="^invalid queue order$"):
            p.reorder_queue(invalid_order)
        assert [song["name"] for song in p.queue] == original_names


@pytest.mark.asyncio
async def test_add_to_queue_assigns_queue_ids(monkeypatch):
    p = MusicPlayer(FakeBot())
    p.is_playing = True
    monkeypatch.setattr("music.os.path.exists", lambda _path: True)

    added = await p.add_to_queue(None, "/tmp/song.mp3", WebUser())

    assert added is True
    assert p.queue[0]["queue_id"]


@pytest.mark.asyncio
async def test_add_stream_to_queue_assigns_queue_ids():
    p = MusicPlayer(FakeBot())
    p.is_playing = True

    added = await p.add_stream_to_queue(
        None,
        {"url": "https://example.com/stream", "title": "Stream"},
        WebUser(),
    )

    assert added is True
    assert p.queue[0]["queue_id"]


def test_set_voice_client():
    p = MusicPlayer(FakeBot())
    vc = MagicMock()
    p.set_voice_client(vc)
    assert p.voice_client is vc
    assert p._get_voice_client(None) is vc


def test_get_voice_client_prefers_stored():
    p = MusicPlayer(FakeBot())
    stored = MagicMock(name="stored")
    guild_vc = MagicMock(name="guild")
    p.voice_client = stored
    interaction = MagicMock()
    interaction.guild.voice_client = guild_vc
    assert p._get_voice_client(interaction) is stored


def test_get_voice_client_none_interaction_without_stored():
    p = MusicPlayer(FakeBot())
    assert p._get_voice_client(None) is None


@pytest.mark.asyncio
async def test_send_message_none_interaction_is_noop():
    p = MusicPlayer(FakeBot())
    result = await p._send_message(None, "hello")
    assert result is None


@pytest.mark.asyncio
async def test_clear_queue_silent_with_no_interaction():
    p = MusicPlayer(FakeBot())
    p.queue.append({"name": "x", "user": WebUser(), "is_stream": False})
    await p.clear_queue(None)
    assert len(p.queue) == 0


@pytest.mark.asyncio
async def test_pause_resume_stop_skip_with_no_interaction():
    p = MusicPlayer(FakeBot())
    vc = MagicMock()
    p.set_voice_client(vc)
    p.is_playing = True
    p.current = {"name": "s", "user": WebUser()}

    await p.pause(None)
    assert p.is_paused is True
    vc.pause.assert_called_once()

    await p.resume(None)
    assert p.is_paused is False
    vc.resume.assert_called_once()

    p.is_playing = True
    p.current = {"name": "s", "user": WebUser()}
    p.queue.append({"name": "next", "user": WebUser(), "file": "/nope", "is_stream": False})
    # stop clears queue and current
    await p.stop(None)
    assert p.is_playing is False
    assert p.current is None
    assert len(p.queue) == 0
    vc.stop.assert_called()


@pytest.mark.asyncio
async def test_skip_only_stops_when_voice_client_present():
    """skip must not call play_next when VC exists — after-callback advances."""
    p = MusicPlayer(FakeBot())
    vc = MagicMock()
    p.set_voice_client(vc)
    p.is_playing = True
    p.current = {"name": "now", "user": WebUser()}
    p.queue.append({
        "file": "/tmp/next.mp3",
        "name": "next.mp3",
        "user": WebUser(),
        "is_stream": False,
    })

    with patch.object(p, "play_next", new_callable=AsyncMock) as mock_next:
        await p.skip(None)
        mock_next.assert_not_called()
    vc.stop.assert_called_once()


@pytest.mark.asyncio
async def test_skip_without_voice_calls_play_next():
    p = MusicPlayer(FakeBot())
    p.voice_client = None
    p.is_playing = True
    p.current = {"name": "now", "user": WebUser()}

    with patch.object(p, "play_next", new_callable=AsyncMock) as mock_next:
        await p.skip(None)
        mock_next.assert_called_once_with(None)


def test_cleanup_clears_voice_client():
    p = MusicPlayer(FakeBot())
    vc = MagicMock()
    p.set_voice_client(vc)
    p.is_playing = True
    p.current = {"name": "x", "user": WebUser()}
    p.queue.append({"name": "q", "user": WebUser()})
    p.cleanup()
    assert p.voice_client is None
    assert p.is_playing is False
    assert p.current is None
    assert len(p.queue) == 0
    vc.stop.assert_called_once()


@pytest.mark.asyncio
async def test_play_next_no_voice_requeues_song():
    """When VC is missing, song must return to front of queue and is_playing False."""
    p = MusicPlayer(FakeBot())
    p.voice_client = None
    user = WebUser()
    song = {
        "file": "/tmp/song.mp3",
        "name": "song.mp3",
        "user": user,
        "is_stream": False,
    }
    p.queue.append(song)

    await p.play_next(None)

    assert p.is_playing is False
    assert p.current is None
    assert len(p.queue) == 1
    assert p.queue[0]["name"] == "song.mp3"


@pytest.mark.asyncio
async def test_add_to_queue_missing_file_returns_false():
    p = MusicPlayer(FakeBot())
    ok = await p.add_to_queue(None, "/nonexistent/path/nope.mp3", WebUser())
    assert ok is False
    assert len(p.queue) == 0


@pytest.mark.asyncio
async def test_play_next_with_none_interaction_uses_voice_client():
    """play_next(interaction=None) should advance when voice_client is set."""
    p = MusicPlayer(FakeBot())
    loop = asyncio.get_running_loop()
    p.bot = MagicMock()
    p.bot.loop = loop

    vc = MagicMock()
    vc.play = MagicMock()
    p.set_voice_client(vc)

    user = WebUser()
    p.queue.append({
        "file": "/tmp/song.mp3",
        "name": "song.mp3",
        "user": user,
        "is_stream": False,
    })

    with patch("discord.FFmpegPCMAudio") as ffmpeg, patch("discord.PCMVolumeTransformer") as vol_xform:
        fake_source = MagicMock()
        ffmpeg.return_value = MagicMock()
        vol_xform.return_value = fake_source

        await p.play_next(None)

    assert p.is_playing is True
    assert p.current["name"] == "song.mp3"
    vc.play.assert_called_once()
    # after callback should call play_next with same interaction (None), not require Interaction
    after_cb = vc.play.call_args.kwargs.get("after") or vc.play.call_args[1].get("after")
    assert after_cb is not None
    # Invoke with error -> should not schedule
    after_cb(Exception("boom"))
    # Invoke with None -> schedules play_next(None); ensure no crash
    after_cb(None)
