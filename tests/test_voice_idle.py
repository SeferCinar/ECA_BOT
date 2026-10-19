"""Tests for leaving a voice channel after it stays empty (no real Discord)."""
import asyncio

import pytest

from voice_idle import VoiceIdleWatcher

TIMEOUT = 0.05


class Member:
    def __init__(self, bot):
        self.bot = bot


class Channel:
    def __init__(self, *members):
        self.members = list(members)


class Guild:
    def __init__(self, channel):
        self.id = 1
        self.channel = channel  # bot's current voice channel, None if not connected


def make_watcher():
    left = []

    async def on_idle(guild):
        left.append(guild.id)
        guild.channel = None

    watcher = VoiceIdleWatcher(TIMEOUT, lambda guild: guild.channel, on_idle)
    return watcher, left


@pytest.mark.asyncio
async def test_leaves_after_timeout_when_only_bots_remain():
    guild = Guild(Channel(Member(bot=True), Member(bot=True)))
    watcher, left = make_watcher()

    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 3)

    assert left == [1]
    assert not watcher.is_pending(1)


@pytest.mark.asyncio
async def test_does_not_start_timer_while_a_human_is_present():
    guild = Guild(Channel(Member(bot=True), Member(bot=False)))
    watcher, left = make_watcher()

    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 3)

    assert left == []
    assert not watcher.is_pending(1)


@pytest.mark.asyncio
async def test_human_joining_cancels_pending_leave():
    channel = Channel(Member(bot=True))
    guild = Guild(channel)
    watcher, left = make_watcher()

    watcher.update(guild)
    assert watcher.is_pending(1)
    channel.members.append(Member(bot=False))
    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 3)

    assert left == []
    assert not watcher.is_pending(1)


@pytest.mark.asyncio
async def test_rechecks_channel_before_leaving():
    """A human who joined without an update reaching the watcher must still keep the bot."""
    channel = Channel(Member(bot=True))
    guild = Guild(channel)
    watcher, left = make_watcher()

    watcher.update(guild)
    channel.members.append(Member(bot=False))
    await asyncio.sleep(TIMEOUT * 3)

    assert left == []


@pytest.mark.asyncio
async def test_repeated_updates_do_not_restart_the_timer():
    guild = Guild(Channel(Member(bot=True)))
    watcher, left = make_watcher()

    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 0.6)
    watcher.update(guild)  # e.g. another bot moving around
    await asyncio.sleep(TIMEOUT * 0.8)

    assert left == [1]


@pytest.mark.asyncio
async def test_disconnect_cancels_pending_leave():
    guild = Guild(Channel(Member(bot=True)))
    watcher, left = make_watcher()

    watcher.update(guild)
    guild.channel = None  # /leave or kicked
    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 3)

    assert left == []
    assert not watcher.is_pending(1)


@pytest.mark.asyncio
async def test_update_during_on_idle_does_not_cancel_cleanup():
    """Disconnecting fires a voice_state_update; that must not cancel the leave in progress."""
    guild = Guild(Channel(Member(bot=True)))
    finished = []

    async def on_idle(g):
        g.channel = None
        watcher.update(g)  # what on_voice_state_update does after disconnect
        await asyncio.sleep(0)
        finished.append(g.id)

    watcher = VoiceIdleWatcher(TIMEOUT, lambda g: g.channel, on_idle)
    watcher.update(guild)
    await asyncio.sleep(TIMEOUT * 3)

    assert finished == [1]
