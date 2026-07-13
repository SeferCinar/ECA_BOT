import discord
from discord.ext import commands
import asyncio
from collections import deque
import os


class WebUser:
    """Pseudo-user for web UI queue attribution."""

    def __init__(self, name: str = "Web UI"):
        self.id = 0
        self.name = name
        self.display_name = name

    @property
    def mention(self) -> str:
        return self.name


class MusicPlayer:
    def __init__(self, bot):
        self.bot = bot
        self.queue = deque()
        self.current = None
        self.volume = 0.5
        self.is_playing = False
        self.is_paused = False
        self.voice_client = None
        self.current_user = None
    
    def set_voice_client(self, voice_client):
        """Store voice client for web path (no Interaction)."""
        self.voice_client = voice_client

    def _get_voice_client(self, interaction):
        """Prefer stored voice_client; fall back to interaction.guild.voice_client."""
        if self.voice_client is not None:
            return self.voice_client
        if interaction is None:
            return None
        return interaction.guild.voice_client
    
    async def _send_message(self, interaction, message, ephemeral=False):
        """Mesaj gönder (hem interaction hem de ctx destekler). Web path: no-op."""
        if interaction is None:
            return None  # web path: no Discord reply
        if hasattr(interaction, 'response') and not interaction.response.is_done():
            return await interaction.response.send_message(message, ephemeral=ephemeral)
        elif hasattr(interaction, 'followup'):
            return await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            return await interaction.send(message)

    def snapshot(self):
        """JSON-serializable player state for web UI / API."""
        def song_dict(s):
            if not s:
                return None
            user = s.get("user")
            user_label = getattr(user, "name", None) or getattr(user, "mention", None) or str(user)
            return {
                "name": s.get("name"),
                "is_stream": bool(s.get("is_stream", False)),
                "user": user_label,
                "webpage_url": s.get("webpage_url") or "",
            }
        return {
            "current": song_dict(self.current),
            "queue": [song_dict(s) for s in list(self.queue)],
            "volume": self.get_volume(),
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
        }
    
    async def add_to_queue(self, interaction, file_path, user):
        """Kuyruğa şarkı ekle (yerel dosya). Returns True on success."""
        if not os.path.exists(file_path):
            await self._send_message(interaction, f"❌ Dosya bulunamadı: {file_path}")
            return False
        
        song_name = os.path.basename(file_path)
        self.queue.append({
            'file': file_path,
            'name': song_name,
            'user': user,
            'is_stream': False
        })
        
        await self._send_message(interaction, f"✅ **{song_name}** kuyruğa eklendi!")
        
        if not self.is_playing and not self.is_paused:
            await self.play_next(interaction)
        return True
    
    async def add_stream_to_queue(self, interaction, stream_info, user):
        """Kuyruğa stream ekle (indirmeden). Returns True on success."""
        self.queue.append({
            'stream_url': stream_info['url'],
            'name': stream_info['title'],
            'user': user,
            'is_stream': True,
            'webpage_url': stream_info.get('webpage_url', '')
        })
        
        await self._send_message(interaction, f"✅ **{stream_info['title']}** kuyruğa eklendi! (🌐 Stream)")
        
        if not self.is_playing and not self.is_paused:
            await self.play_next(interaction)
        return True
    
    async def play_next(self, interaction):
        """Sıradaki şarkıyı çal. interaction may be None for web path."""
        if self.is_paused:
            return
        
        if len(self.queue) == 0:
            self.is_playing = False
            self.current = None
            await self._send_message(interaction, "📭 Kuyruk boş!")
            return
        
        song = self.queue.popleft()
        self.current = song
        self.is_playing = True
        
        voice_client = self._get_voice_client(interaction)
        if voice_client is None:
            # Don't drop the track or leave is_playing True without a client
            self.queue.appendleft(song)
            self.current = None
            self.is_playing = False
            await self._send_message(interaction, "❌ Ses kanalına bağlı değilim!")
            return
        
        self.voice_client = voice_client
        
        # Stream mi yoksa yerel dosya mı kontrol et
        if self.current.get('is_stream', False):
            # Stream için FFmpeg ayarları
            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            source = discord.FFmpegPCMAudio(
                self.current['stream_url'],
                **ffmpeg_options
            )
            source_type = "🌐"
        else:
            # Yerel dosya için FFmpeg source
            source = discord.FFmpegPCMAudio(
                self.current['file'],
                options='-vn'
            )
            source_type = "📁"
        
        # Volume ayarla
        source = discord.PCMVolumeTransformer(source, volume=self.volume)
        
        # after-callback must not require a live Interaction; interaction may be None (web)
        def _after(err):
            if err is not None:
                return
            if self.bot is None or getattr(self.bot, "loop", None) is None:
                return
            asyncio.run_coroutine_threadsafe(
                self.play_next(interaction),
                self.bot.loop,
            )

        self.voice_client.play(source, after=_after)
        
        await self._send_message(interaction, f"{source_type} Şimdi çalıyor: **{self.current['name']}** (İsteyen: {self.current['user'].mention})")
    
    async def skip(self, interaction):
        """Şarkıyı geç. Rely on voice after-callback to advance; only call play_next if no VC."""
        if not self.is_playing:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return
        
        if self.voice_client:
            # stop() fires after-callback which calls play_next — do not double-advance
            self.voice_client.stop()
        else:
            await self.play_next(interaction)
        
        await self._send_message(interaction, "⏭️ Şarkı geçildi!")
    
    async def stop(self, interaction):
        """Müziği durdur"""
        if not self.is_playing and not self.is_paused:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return
        
        self.queue.clear()
        if self.voice_client:
            self.voice_client.stop()
        
        self.is_playing = False
        self.is_paused = False
        self.current = None
        await self._send_message(interaction, "⏹️ Müzik durduruldu ve kuyruk temizlendi!")
    
    async def pause(self, interaction):
        """Müziği duraklat"""
        if not self.is_playing:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return
        
        if self.is_paused:
            await self._send_message(interaction, "❌ Müzik zaten duraklatılmış!")
            return
        
        if self.voice_client:
            self.voice_client.pause()
        
        self.is_paused = True
        await self._send_message(interaction, "⏸️ Müzik duraklatıldı!")
    
    async def resume(self, interaction):
        """Müziği devam ettir"""
        if not self.is_paused:
            await self._send_message(interaction, "❌ Müzik duraklatılmamış!")
            return
        
        if self.voice_client:
            self.voice_client.resume()
        
        self.is_paused = False
        await self._send_message(interaction, "▶️ Müzik devam ediyor!")
    
    async def show_queue(self, interaction):
        """Kuyruğu göster"""
        if len(self.queue) == 0 and self.current is None:
            await self._send_message(interaction, "📭 Kuyruk boş!")
            return
        
        queue_list = []
        if self.current:
            queue_list.append(f"🎵 **Şimdi çalıyor:** {self.current['name']}")
        
        if len(self.queue) > 0:
            queue_list.append("\n📋 **Kuyruk:**")
            for i, song in enumerate(list(self.queue)[:10], 1):
                queue_list.append(f"{i}. {song['name']}")
            
            if len(self.queue) > 10:
                queue_list.append(f"... ve {len(self.queue) - 10} şarkı daha")
        
        await self._send_message(interaction, "\n".join(queue_list))
    
    async def now_playing(self, interaction):
        """Şu an çalan şarkıyı göster"""
        if self.current is None:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return
        
        status = "⏸️ Duraklatıldı" if self.is_paused else "▶️ Çalıyor"
        await self._send_message(interaction,
            f"{status}\n"
            f"🎵 **{self.current['name']}**\n"
            f"👤 İsteyen: {self.current['user'].mention}"
        )
    
    def get_volume(self):
        """Mevcut ses seviyesini al"""
        return int(self.volume * 100)
    
    async def set_volume(self, interaction, volume):
        """Ses seviyesini ayarla"""
        self.volume = volume
        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = volume
    
    async def clear_queue(self, interaction):
        """Kuyruğu temizle"""
        count = len(self.queue)
        self.queue.clear()
        await self._send_message(interaction, f"🗑️ Kuyruktan {count} şarkı silindi!")
    
    async def shuffle_queue(self, interaction):
        """Kuyruğu karıştır"""
        if len(self.queue) < 2:
            await self._send_message(interaction, "❌ Karıştırmak için en az 2 şarkı olmalı!")
            return
        
        import random
        queue_list = list(self.queue)
        random.shuffle(queue_list)
        self.queue = deque(queue_list)
        await self._send_message(interaction, "🔀 Kuyruk karıştırıldı!")
    
    def cleanup(self):
        """Temizlik — stop playback and clear voice client reference."""
        if self.voice_client:
            self.voice_client.stop()
        self.voice_client = None
        self.queue.clear()
        self.is_playing = False
        self.is_paused = False
        self.current = None
