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
