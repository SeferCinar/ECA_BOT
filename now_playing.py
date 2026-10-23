"""'Şimdi çalıyor' kartı: kanalda tek bir embed mesajı ve kontrol butonları.

Şarkı değişince, duraklatınca ya da ayar değişince aynı mesaj düzenlenir; çalarken ilerleme
çubuğu belli aralıkla güncellenir. Mesaj bot token'ıyla atılır, 15 dk'da süresi dolan
interaction token'ına bağlı değildir. Web panelinden/eklentiden eklenen şarkılar da görünür.
"""
import asyncio

import discord

from music import AUDIO_FILTERS, LOOP_MODES, format_time, song_thumbnail

BAR_WIDTH = 16


def progress_bar(position, duration, width=BAR_WIDTH):
    """`1:23` ▰▰▰▰▱▱▱▱ `3:45` — süre bilinmiyorsa (canlı yayın vb.) yalnızca geçen süre."""
    if not duration:
        return f"`{format_time(position)}` 🔴"
    filled = max(0, min(width, int(width * position / duration)))
    return f"`{format_time(position)}` {'▰' * filled}{'▱' * (width - filled)} `{format_time(duration)}`"


def _clip(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _user_label(user):
    return getattr(user, "mention", None) or str(user)


def build_embed(player):
    """Çalan şarkının embed'i (player.current dolu olmalı)."""
    song = player.current
    if player.is_loading:
        status, color = "⏳ Hazırlanıyor", discord.Color.light_grey()
        description = "Stream adresi alınıyor…"
    else:
        if player.is_paused:
            status, color = "⏸️ Duraklatıldı", discord.Color.dark_grey()
        else:
            status, color = "▶️ Şimdi çalıyor", discord.Color.blurple()
        description = progress_bar(player.position(), song.get("duration"))

    url = song.get("webpage_url") or ""
    embed = discord.Embed(
        title=_clip(song.get("name"), 256),
        url=url if url.startswith(("https://", "http://")) else None,
        description=description,
        color=color,
    )
    embed.set_author(name=status)
    thumbnail = song_thumbnail(song)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    duration = song.get("duration")
    embed.add_field(name="İsteyen", value=_user_label(song.get("user")), inline=True)
    embed.add_field(name="Süre", value=format_time(duration) if duration else "Bilinmiyor", inline=True)
    embed.add_field(name="Kuyruk", value=f"{len(player.queue)} şarkı" if player.queue else "Boş", inline=True)
    if player.queue:
        upcoming = discord.utils.escape_markdown(_clip(player.queue[0].get("name"), 200))
        embed.add_field(name="Sıradaki", value=upcoming, inline=False)

    footer = [f"🔊 %{player.get_volume()}"]
    if player.loop_mode != "off":
        footer.append(f"{'🔂' if player.loop_mode == 'song' else '🔁'} Döngü: {LOOP_MODES[player.loop_mode]}")
    if player.filter:
        footer.append(f"🎛️ {AUDIO_FILTERS[player.filter][0]}")
    if player.autoplay:
        footer.append("📻 Autoplay")
    embed.set_footer(text=" · ".join(footer))
    return embed


def presence_text(players):
    """Bot durumunda ("... dinliyor") gösterilecek metin; çalan yoksa None.

    Bot durumu tüm sunucular için tek; birden çok sunucuda çalıyorsa ilki gösterilir.
    """
    for player in players:
        song = player.current
        if song is not None and player.is_playing and not player.is_loading:
            return _clip(("⏸ " if player.is_paused else "") + (song.get("name") or ""), 128)
    return None


def idle_embed():
    return discord.Embed(
        description="⏹️ Çalma bitti. `/play` ile yeni şarkı ekleyebilirsin.",
        color=discord.Color.dark_grey(),
    )


def _style(on):
    return discord.ButtonStyle.primary if on else discord.ButtonStyle.secondary


class NowPlayingView(discord.ui.View):
    """Kart butonları. custom_id'ler sabit: bot.py bu view'ı kalıcı kaydettiği için
    bot yeniden başladıktan sonra eski karttaki butonlar da yanıt verir."""

    def __init__(self, get_player, player=None):
        super().__init__(timeout=None)
        self.get_player = get_player  # guild_id -> MusicPlayer
        if player is not None:
            self.pause_button.emoji = "▶️" if player.is_paused else "⏸️"
            self.pause_button.style = discord.ButtonStyle.success if player.is_paused else discord.ButtonStyle.secondary
            self.loop_button.emoji = "🔂" if player.loop_mode == "song" else "🔁"
            self.loop_button.style = _style(player.loop_mode != "off")
            self.autoplay_button.style = _style(player.autoplay)

    async def _act(self, interaction, action):
        """action(player) hata metni döndürürse sadece basana gösterilir; kart kendisi güncellenir."""
        error = await action(self.get_player(interaction.guild_id))
        if error:
            await interaction.response.send_message(error, ephemeral=True)
        else:
            await interaction.response.defer()

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="np:previous", row=0)
    async def previous_button(self, interaction, button):
        async def action(player):
            if player.current is None and not player.history:
                return "❌ Önceki şarkı yok!"
            await player.previous(None)
        await self._act(interaction, action)

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, custom_id="np:pause", row=0)
    async def pause_button(self, interaction, button):
        async def action(player):
            if player.current is None:
                return "❌ Şu anda hiçbir şarkı çalmıyor!"
            if player.is_paused:
                await player.resume(None)
            else:
                await player.pause(None)
        await self._act(interaction, action)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="np:skip", row=0)
    async def skip_button(self, interaction, button):
        async def action(player):
            if not player.is_playing:
                return "❌ Şu anda hiçbir şarkı çalmıyor!"
            await player.skip(None)
        await self._act(interaction, action)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="np:shuffle", row=1)
    async def shuffle_button(self, interaction, button):
        async def action(player):
            if len(player.queue) < 2:
                return "❌ Karıştırmak için en az 2 şarkı olmalı!"
            await player.shuffle_queue(None)
        await self._act(interaction, action)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="np:loop", row=1)
    async def loop_button(self, interaction, button):
        async def action(player):
            player.cycle_loop()
        await self._act(interaction, action)

    @discord.ui.button(emoji="📻", style=discord.ButtonStyle.secondary, custom_id="np:autoplay", row=1)
    async def autoplay_button(self, interaction, button):
        async def action(player):
            player.set_autoplay(not player.autoplay)
        await self._act(interaction, action)


class NowPlayingCard:
    """Bir sunucunun 'Şimdi çalıyor' mesajı.

    Kanal: channel_id (NOW_PLAYING_CHANNEL_ID, bu sunucudaysa), yoksa son müzik komutunun
    yazıldığı kanal. Çalma bitince kart 'bitti' durumuna geçer; sonraki çalmada silinip
    en alta yenisi atılır, böylece kanalda hep tek kart olur.
    """

    TICK_SECONDS = 15  # çalarken ilerleme çubuğunu bu aralıkla güncelle
    MIN_EDIT_INTERVAL = 1.0  # art arda gelen değişiklikleri birleştir

    def __init__(self, player, channel_id=None, guild_id=None):
        self.player = player
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.fallback_channel = None
        self.message = None
        self.ended = False
        self._configured = None
        self._dirty = False
        self._task = None
        self._ticker = None

    def refresh(self):
        """Kartı arka planda güncelle; çağıran Discord'u beklemez."""
        if self.channel_id is None and self.fallback_channel is None:
            return
        self._dirty = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self):
        while self._dirty:
            self._dirty = False
            try:
                await self._render()
            except Exception as e:
                print(f"⚠️ Şimdi çalıyor kartı güncellenemedi: {e}", flush=True)
            await asyncio.sleep(self.MIN_EDIT_INTERVAL)

    async def _channel(self):
        if self.channel_id is not None and self._configured is None:
            bot = self.player.bot
            try:
                channel_id = int(self.channel_id)
                self._configured = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            except (ValueError, discord.HTTPException) as e:
                print(f"⚠️ NOW_PLAYING_CHANNEL_ID={self.channel_id} kanalı bulunamadı: {e}", flush=True)
                self.channel_id = None
        guild = getattr(self._configured, "guild", None)
        if self._configured is not None and (self.guild_id is None or guild is None or guild.id == self.guild_id):
            return self._configured
        return self.fallback_channel

    async def _delete(self):
        try:
            await self.message.delete()
        except discord.HTTPException:
            pass  # elle silinmiş olabilir
        self.message = None

    async def _render(self):
        player = self.player
        channel = await self._channel()
        if channel is None:
            return
        if self.message is not None and (
            self.message.channel.id != channel.id or (self.ended and player.current is not None)
        ):
            await self._delete()  # yeni çalma ya da kanal değişti: yeni kart en altta olsun

        if player.current is None:
            if self.message is not None and not self.ended:
                await self.message.edit(embed=idle_embed(), view=None)
                self.ended = True
            return

        embed = build_embed(player)
        view = NowPlayingView(lambda _guild_id: player, player)
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=view)
            except discord.NotFound:
                self.message = None
        if self.message is None:
            self.message = await channel.send(embed=embed, view=view)
            self.ended = False
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.create_task(self._tick())

    async def _tick(self):
        while self.player.current is not None and self.message is not None:
            await asyncio.sleep(self.TICK_SECONDS)
            if self.player.is_playing and not self.player.is_paused:
                self.refresh()
