"""'Şimdi çalıyor' kartı: tek mesaj, düzenleme, kanal seçimi ve butonlar (gerçek Discord yok)."""
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from music import MusicPlayer, WebUser
from now_playing import NowPlayingCard, NowPlayingView, build_embed, progress_bar


@pytest.fixture(autouse=True)
def no_ffmpeg():
    with patch("discord.FFmpegPCMAudio"), patch("discord.PCMVolumeTransformer"):
        yield


def song(name, **extra):
    vid = (name * 11)[:11]
    return {"name": name, "user": WebUser("Ali"), "is_stream": True, "stream_url": f"https://s/{vid}",
            "webpage_url": f"https://www.youtube.com/watch?v={vid}", **extra}


class FakeChannel:
    def __init__(self, channel_id=10, guild_id=1):
        self.id = channel_id
        self.guild = MagicMock(id=guild_id)
        self.sent = []
        self.send = AsyncMock(side_effect=self._send)

    async def _send(self, **kwargs):
        message = MagicMock()
        message.channel = self
        message.edit = AsyncMock()
        message.delete = AsyncMock()
        message.kwargs = kwargs
        self.sent.append(message)
        return message


def make_player(channel=None, channel_id=None, guild_id=1):
    bot = MagicMock()
    bot.loop = None
    player = MusicPlayer(bot)
    vc = MagicMock()
    vc.is_playing.return_value = True
    player.set_voice_client(vc)
    player.card = NowPlayingCard(player, channel_id, guild_id)
    player.card.MIN_EDIT_INTERVAL = 0
    player.card.fallback_channel = channel
    return player


async def settle(card):
    while card._task is not None and not card._task.done():
        await card._task


def test_progress_bar():
    assert progress_bar(0, 100, width=10) == "`0:00` ▱▱▱▱▱▱▱▱▱▱ `1:40`"
    assert progress_bar(50, 100, width=10) == "`0:50` ▰▰▰▰▰▱▱▱▱▱ `1:40`"
    assert progress_bar(500, 100, width=10) == "`8:20` ▰▰▰▰▰▰▰▰▰▰ `1:40`"
    assert progress_bar(42, None) == "`0:42` 🔴"


@pytest.mark.asyncio
async def test_embed_shows_song_details():
    player = make_player()
    player.queue.extend([song("a", duration=225, thumbnail="https://img/a.jpg"), song("b")])
    await player.play_next(None)
    player.set_loop("song")
    player.filter = "nightcore"
    player.set_autoplay(True)

    embed = build_embed(player)

    assert embed.title == "a"
    assert embed.url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert embed.author.name == "▶️ Şimdi çalıyor"
    assert embed.thumbnail.url == "https://img/a.jpg"
    fields = {f.name: f.value for f in embed.fields}
    assert fields == {"İsteyen": "Ali", "Süre": "3:45", "Kuyruk": "1 şarkı", "Sıradaki": "b"}
    assert "3:45" in embed.description
    assert embed.footer.text == "🔊 %50 · 🔂 Döngü: Şarkı · 🎛️ Nightcore · 📻 Autoplay"


@pytest.mark.asyncio
async def test_embed_while_stream_is_resolving():
    player = make_player()
    pending = song("a", stream_url=None)
    player.current = pending
    player._resolving_song = pending

    embed = build_embed(player)

    assert embed.author.name == "⏳ Hazırlanıyor"
    assert embed.thumbnail.url == "https://i.ytimg.com/vi/aaaaaaaaaaa/hqdefault.jpg"


@pytest.mark.asyncio
async def test_card_edits_one_message_across_song_changes():
    channel = FakeChannel()
    player = make_player(channel)
    player.queue.extend([song("a"), song("b")])

    await player.play_next(None)
    await settle(player.card)
    await player.play_next(None)  # a bitti -> b
    await settle(player.card)

    assert channel.send.await_count == 1
    message = channel.sent[0]
    assert message.edit.await_args.kwargs["embed"].title == "b"
    assert isinstance(message.edit.await_args.kwargs["view"], NowPlayingView)


@pytest.mark.asyncio
async def test_card_goes_idle_then_reposts_for_next_session():
    channel = FakeChannel()
    player = make_player(channel)
    player.queue.append(song("a"))
    await player.play_next(None)
    await settle(player.card)

    await player.play_next(None)  # kuyruk bitti
    await settle(player.card)
    first = channel.sent[0]
    assert first.edit.await_args.kwargs["view"] is None
    assert "Çalma bitti" in first.edit.await_args.kwargs["embed"].description

    player.queue.append(song("b"))
    await player.play_next(None)
    await settle(player.card)

    first.delete.assert_awaited_once()
    assert channel.send.await_count == 2
    assert channel.sent[1].kwargs["embed"].title == "b"


@pytest.mark.asyncio
async def test_card_resends_when_message_was_deleted():
    channel = FakeChannel()
    player = make_player(channel)
    player.queue.extend([song("a"), song("b")])
    await player.play_next(None)
    await settle(player.card)
    channel.sent[0].edit.side_effect = discord.NotFound(MagicMock(status=404), "Unknown Message")

    await player.play_next(None)
    await settle(player.card)

    assert channel.send.await_count == 2


@pytest.mark.asyncio
async def test_card_uses_configured_channel_only_in_its_guild():
    fallback, configured = FakeChannel(10), FakeChannel(20, guild_id=1)
    player = make_player(fallback, channel_id="20", guild_id=1)
    player.bot.get_channel.return_value = configured
    player.queue.append(song("a"))
    await player.play_next(None)
    await settle(player.card)
    assert configured.send.await_count == 1
    assert fallback.send.await_count == 0

    other = make_player(fallback, channel_id="20", guild_id=2)
    other.bot.get_channel.return_value = configured
    other.queue.append(song("a"))
    await other.play_next(None)
    await settle(other.card)
    assert fallback.send.await_count == 1


@pytest.mark.asyncio
async def test_card_falls_back_when_configured_channel_is_missing():
    fallback = FakeChannel()
    player = make_player(fallback, channel_id="99")
    player.bot.get_channel.return_value = None
    player.bot.fetch_channel = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Channel"))
    player.queue.append(song("a"))

    await player.play_next(None)
    await settle(player.card)

    assert fallback.send.await_count == 1
    assert player.card.channel_id is None  # bir daha denenmez


@pytest.mark.asyncio
async def test_card_without_channel_does_nothing():
    player = make_player()
    player.queue.append(song("a"))
    await player.play_next(None)
    assert player.card._task is None


@pytest.mark.asyncio
async def test_rapid_changes_collapse_into_few_edits():
    channel = FakeChannel()
    player = make_player(channel)
    player.queue.extend([song("a"), song("b"), song("c")])
    await player.play_next(None)
    await settle(player.card)

    for _ in range(10):
        player.set_loop("queue")
    await settle(player.card)

    assert channel.sent[0].edit.await_count <= 2


def interaction(guild_id=1):
    i = MagicMock()
    i.guild_id = guild_id
    i.response.defer = AsyncMock()
    i.response.send_message = AsyncMock()
    return i


@pytest.mark.asyncio
async def test_view_reflects_state():
    player = make_player()
    player.current = song("a")
    player.is_paused = True
    player.loop_mode = "song"
    player.autoplay = True

    view = NowPlayingView(lambda _: player, player)

    assert str(view.pause_button.emoji) == "▶️"
    assert view.pause_button.style == discord.ButtonStyle.success
    assert str(view.loop_button.emoji) == "🔂"
    assert view.loop_button.style == discord.ButtonStyle.primary
    assert view.autoplay_button.style == discord.ButtonStyle.primary
    assert {item.custom_id for item in view.children} == {"np:previous", "np:pause", "np:skip", "np:shuffle", "np:loop", "np:autoplay"}


@pytest.mark.asyncio
async def test_view_buttons_control_player():
    player = make_player()
    player.queue.extend([song("a"), song("b"), song("c")])
    await player.play_next(None)
    view = NowPlayingView(lambda _: player)

    i = interaction()
    await view.pause_button.callback(i)
    assert player.is_paused is True
    i.response.defer.assert_awaited_once()

    await view.pause_button.callback(interaction())
    assert player.is_paused is False

    await view.loop_button.callback(interaction())
    assert player.loop_mode == "song"

    await view.autoplay_button.callback(interaction())
    assert player.autoplay is True

    await view.skip_button.callback(interaction())
    player.voice_client.stop.assert_called_once()


@pytest.mark.asyncio
async def test_view_reports_errors_only_to_clicker():
    player = make_player()  # hiçbir şey çalmıyor
    view = NowPlayingView(lambda _: player)

    i = interaction()
    await view.skip_button.callback(i)
    i.response.send_message.assert_awaited_once_with("❌ Şu anda hiçbir şarkı çalmıyor!", ephemeral=True)

    i = interaction()
    await view.shuffle_button.callback(i)
    i.response.send_message.assert_awaited_once_with("❌ Karıştırmak için en az 2 şarkı olmalı!", ephemeral=True)


def test_presence_text_shows_first_playing_song():
    from now_playing import presence_text

    idle, loading, playing, paused = (make_player() for _ in range(4))
    loading.current, loading.is_playing, loading._resolving_song = song("x"), True, song("x")
    playing.current, playing.is_playing = song("a"), True
    paused.current, paused.is_playing, paused.is_paused = song("p"), True, True

    assert presence_text([idle, loading, playing]) == "a"
    assert presence_text([paused]) == "⏸ p"
    assert presence_text([idle]) is None
    playing.current = song("x" * 300)
    assert len(presence_text([playing])) == 128


@pytest.mark.asyncio
async def test_previous_button():
    player = make_player()
    player.queue.extend([song("a"), song("b")])
    await player.play_next(None)
    await player.play_next(None)  # a bitti
    view = NowPlayingView(lambda _: player)

    await view.previous_button.callback(interaction())

    player.voice_client.stop.assert_called_once()
    assert [s["name"] for s in player.queue] == ["a", "b"]

    empty = NowPlayingView(lambda _: make_player())
    i = interaction()
    await empty.previous_button.callback(i)
    i.response.send_message.assert_awaited_once_with("❌ Önceki şarkı yok!", ephemeral=True)
