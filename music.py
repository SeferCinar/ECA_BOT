import discord
from discord.ext import commands
import asyncio
from collections import deque
import os
import re
from uuid import uuid4

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def video_id_from_url(url):
    """YouTube / YouTube Music linkinden video ID'si (bulunamazsa None)."""
    match = _VIDEO_ID_RE.search(url or "")
    return match.group(1) if match else None


class WebUser:
    """Pseudo-user for web UI queue attribution."""

    def __init__(self, name: str = "Web UI"):
        self.id = 0
        self.name = name
        self.display_name = name

    @property
    def mention(self) -> str:
        return self.name


AUTOPLAY_USER = WebUser(name="Autoplay")


class MusicPlayer:
    AUTOPLAY_HISTORY = 100  # bu kadar son çalınan şarkı autoplay'de tekrar seçilmez
    AUTOPLAY_ATTEMPTS = 3  # stream alınamazsa denenecek aday sayısı

    def __init__(self, bot, downloader=None):
        self.bot = bot
        self.downloader = downloader
        self.queue = deque()
        self.current = None
        self.volume = 0.5
        self.is_playing = False
        self.is_paused = False
        self.voice_client = None
        self.current_user = None
        self.autoplay = False
        self.played_ids = deque(maxlen=self.AUTOPLAY_HISTORY)
        self._autoplay_pool = []
        self._autoplay_pending = False
        self._epoch = 0  # stop/skip/cleanup/autoplay kapatma sırasında süren aramaları geçersiz kılar
        self._resolving_song = None  # stream adresi alınmakta olan şarkı
        self._start_task = None

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

    def _ensure_queue_id(self, song):
        song.setdefault("queue_id", uuid4().hex)
        return song["queue_id"]

    def reorder_queue(self, queue_ids: list[str]) -> None:
        current = list(self.queue)
        by_id = {self._ensure_queue_id(song): song for song in current}
        if len(by_id) != len(current) or len(queue_ids) != len(current) or set(queue_ids) != set(by_id):
            raise ValueError("invalid queue order")
        self.queue = deque(by_id[queue_id] for queue_id in queue_ids)

    def remove_from_queue(self, queue_id: str):
        """Kuyruktan queue_id ile şarkı çıkar. Returns removed song or None."""
        for index, song in enumerate(self.queue):
            if self._ensure_queue_id(song) == queue_id:
                del self.queue[index]
                return song
        return None

    async def remove_at(self, interaction, position: int):
        """Kuyruktan sıra numarasıyla (1'den başlar) şarkı çıkar. Returns removed song or None."""
        if len(self.queue) == 0:
            await self._send_message(interaction, "📭 Kuyruk boş!", ephemeral=True)
            return None
        if position < 1 or position > len(self.queue):
            await self._send_message(
                interaction,
                f"❌ Geçersiz sıra! Kuyrukta {len(self.queue)} şarkı var.",
                ephemeral=True,
            )
            return None
        song = self.queue[position - 1]
        del self.queue[position - 1]
        await self._send_message(interaction, f"🗑️ **{song['name']}** kuyruktan kaldırıldı!")
        return song

    def snapshot(self):
        """JSON-serializable player state for web UI / API."""
        def song_dict(s, include_queue_id=False):
            if not s:
                return None
            user = s.get("user")
            user_label = getattr(user, "name", None) or getattr(user, "mention", None) or str(user)
            result = {
                "name": s.get("name"),
                "is_stream": bool(s.get("is_stream", False)),
                "user": user_label,
                "webpage_url": s.get("webpage_url") or "",
            }
            if include_queue_id:
                result["queue_id"] = self._ensure_queue_id(s)
            return result
        return {
            "current": song_dict(self.current),
            "queue": [song_dict(s, include_queue_id=True) for s in list(self.queue)],
            "volume": self.get_volume(),
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "autoplay": self.autoplay,
            "is_loading": self._resolving_song is not None,
        }
    
    async def add_to_queue(self, interaction, file_path, user):
        """Kuyruğa şarkı ekle (yerel dosya). Returns True on success."""
        if not os.path.exists(file_path):
            await self._send_message(interaction, f"❌ Dosya bulunamadı: {file_path}")
            return False
        
        song_name = os.path.basename(file_path)
        song = {
            'file': file_path,
            'name': song_name,
            'user': user,
            'is_stream': False,
        }
        self._ensure_queue_id(song)
        self.queue.append(song)
        
        await self._send_message(interaction, f"✅ **{song_name}** kuyruğa eklendi!")
        
        if not self.is_playing and not self.is_paused:
            await self.play_next(interaction)
        return True
    
    async def add_stream_to_queue(self, interaction, stream_info, user):
        """Kuyruğa stream ekle (indirmeden). Returns True on success."""
        song = {
            'stream_url': stream_info['url'],
            'name': stream_info['title'],
            'user': user,
            'is_stream': True,
            'webpage_url': stream_info.get('webpage_url', ''),
        }
        self._ensure_queue_id(song)
        self.queue.append(song)
        
        await self._send_message(interaction, f"✅ **{stream_info['title']}** kuyruğa eklendi! (🌐 Stream)")
        
        if not self.is_playing and not self.is_paused:
            await self.play_next(interaction)
        return True
    
    async def play_next(self, interaction):
        """Sıradaki şarkıyı çal. interaction may be None for web path."""
        if self.is_paused:
            return

        finished = self.current  # stop/cleanup sonrası None: o durumda autoplay devreye girmez
        if len(self.queue) == 0:
            self.is_playing = False
            self.current = None
            if self.autoplay and finished is not None and await self._autoplay_from(finished):
                return
            await self._send_message(interaction, "📭 Kuyruk boş!")
            return

        song = self.queue.popleft()
        self.current = song
        self.is_playing = True
        played_id = video_id_from_url(song.get('webpage_url'))
        if played_id:
            self.played_ids.append(played_id)
        
        voice_client = self._get_voice_client(interaction)
        if voice_client is None:
            # Don't drop the track or leave is_playing True without a client
            self.queue.appendleft(song)
            self.current = None
            self.is_playing = False
            await self._send_message(interaction, "❌ Ses kanalına bağlı değilim!")
            return
        
        self.voice_client = voice_client

        # Hızlı eklenen şarkılar: stream adresi çalma sırası gelince alınır
        if song.get('is_stream') and not song.get('stream_url'):
            ready = await self._resolve_stream(song)
            if ready is None:
                return  # stop/skip/leave araya girdi
            if not ready:
                await self._send_message(interaction, f"⚠️ **{song['name']}** çalınamadı, sıradakine geçiyorum.")
                await self.play_next(interaction)
                return

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
        if self.is_paused:  # stream adresi alınırken duraklatıldıysa
            self.voice_client.pause()

        await self._send_message(interaction, f"{source_type} Şimdi çalıyor: **{self.current['name']}** (İsteyen: {self.current['user'].mention})")
    
    async def _resolve_stream(self, song):
        """Kuyruktaki şarkının stream adresini al.

        Returns True if ready, False if it failed, None if stop/skip/leave happened meanwhile.
        """
        epoch = self._epoch
        self._resolving_song = song
        info = None
        try:
            if self.downloader is not None:
                info = await self.downloader.get_stream_url(song['webpage_url'])
        except Exception as e:
            print(f"⚠️ Stream alınamadı ({song['name']}): {e}", flush=True)
        finally:
            # skip sonrası sıradaki şarkı çoktan çözülmeye başlamış olabilir; onunkini silme
            if self._resolving_song is song:
                self._resolving_song = None
        if epoch != self._epoch or self.current is not song:
            return None
        if not info:
            return False
        song['stream_url'] = info['url']
        return True

    def enqueue_tracks(self, tracks, user):
        """Şarkıları stream adresini almadan kuyruğa ekle (adres çalma sırası gelince alınır).

        tracks: [{video_id, title, artists?}]. Returns the queued song dicts.
        """
        added = []
        for t in tracks:
            title = t.get('title') or t['video_id']
            song = {
                'name': f"{t['artists']} - {title}" if t.get('artists') else title,
                'user': user,
                'is_stream': True,
                'stream_url': None,
                'webpage_url': f"https://www.youtube.com/watch?v={t['video_id']}",
            }
            self._ensure_queue_id(song)
            self.queue.append(song)
            added.append(song)
        return added

    def start_if_idle(self):
        """Çalmıyorsa sıradakini başlat; stream adresi arka planda alınır, çağıran beklemez."""
        if self.is_playing or self.is_paused:
            return
        if self._start_task is not None and not self._start_task.done():
            return  # aynı anda gelen eklemeler ikinci kez başlatmasın
        self._start_task = asyncio.create_task(self.play_next(None))

    def set_autoplay(self, enabled):
        """Autoplay'i aç/kapat. Kapatınca süren bir autoplay araması iptal olur."""
        self.autoplay = bool(enabled)
        if not self.autoplay:
            self._epoch += 1
            self._autoplay_pool = []

    def _next_autoplay_candidate(self):
        """Havuzdan daha önce çalınmamış ilk şarkıyı çıkar."""
        while self._autoplay_pool:
            candidate = self._autoplay_pool.pop(0)
            if candidate['id'] not in self.played_ids:
                return candidate
        return None

    async def _autoplay_from(self, finished):
        """Kuyruk bitince benzer bir şarkı ekleyip çal.

        Returns True if handled (a song was queued, or the user acted meanwhile),
        False if nothing could be found.
        """
        if self.downloader is None or self._autoplay_pending:
            return self._autoplay_pending
        seed = video_id_from_url(finished.get('webpage_url')) or (self.played_ids[-1] if self.played_ids else None)
        if seed is None:
            return False

        epoch = self._epoch
        self._autoplay_pending = True
        info = None
        try:
            # Kullanıcının seçtiği şarkı bittiyse onun radyosunu baştan kur; autoplay
            # şarkıları arasında havuz bitene kadar aynı radyodan devam et.
            if not finished.get('autoplay') or not self._autoplay_pool:
                self._autoplay_pool = await self.downloader.get_related_videos(seed)
            for _ in range(self.AUTOPLAY_ATTEMPTS):
                candidate = self._next_autoplay_candidate()
                if candidate is None:
                    break
                try:
                    info = await self.downloader.get_stream_url(
                        f"https://www.youtube.com/watch?v={candidate['id']}"
                    )
                except Exception as e:
                    print(f"⚠️ Autoplay stream alınamadı ({candidate['id']}): {e}", flush=True)
                if info:
                    break
        except Exception as e:
            print(f"⚠️ Autoplay hatası: {e}", flush=True)
        finally:
            self._autoplay_pending = False

        # Arama sürerken stop/leave/autoplay kapatma ya da yeni şarkı eklendiyse vazgeç
        if epoch != self._epoch or not self.autoplay or self.is_playing or self.queue:
            return True
        if not info:
            return False

        song = {
            'stream_url': info['url'],
            'name': info['title'],
            'user': AUTOPLAY_USER,
            'is_stream': True,
            'webpage_url': info.get('webpage_url', ''),
            'autoplay': True,
        }
        self._ensure_queue_id(song)
        self.queue.append(song)
        await self.play_next(None)
        return True

    async def skip(self, interaction):
        """Şarkıyı geç. Rely on voice after-callback to advance; only call play_next if no VC."""
        if not self.is_playing:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return
        
        if self._resolving_song is not None:
            # Stream adresi alınırken VC'de çalan bir şey yok: o şarkıyı bırak, sıradakine geç.
            # Beklemeden başlat; Discord yanıtı 3 sn içinde gitmeli.
            self._epoch += 1
            asyncio.create_task(self.play_next(None))
        elif self.voice_client:
            # stop() fires after-callback which calls play_next — do not double-advance
            self.voice_client.stop()
        else:
            await self.play_next(interaction)
        
        await self._send_message(interaction, "⏭️ Şarkı geçildi!")
    
    async def stop(self, interaction):
        """Müziği durdur"""
        if not self.is_playing and not self.is_paused and not self._autoplay_pending:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return

        self._epoch += 1  # süren autoplay aramasını iptal et
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
        self._epoch += 1  # süren autoplay aramasını iptal et
        if self.voice_client:
            self.voice_client.stop()
        self.voice_client = None
        self.queue.clear()
        self.is_playing = False
        self.is_paused = False
        self.current = None
