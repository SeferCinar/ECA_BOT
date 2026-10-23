import discord
from discord.ext import commands
import asyncio
from collections import deque
import os
import re
import select
import subprocess
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from mixer import CrossfadeMixer

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)

# Ses filtreleri (FFmpeg -af): ad -> (etiket, filtre zinciri, hız çarpanı)
AUDIO_FILTERS = {
    'bassboost': ('Bass Boost', 'bass=g=8:f=110:w=0.6,alimiter=limit=0.95', 1.0),
    'nightcore': ('Nightcore', 'aresample=48000,asetrate=60000,aresample=48000', 1.25),
    'slowed': ('Slowed + Reverb', 'aresample=48000,asetrate=38400,aresample=48000,aecho=0.8:0.65:60|120:0.4|0.25', 0.8),
    '8d': ('8D', 'aformat=channel_layouts=stereo,apulsator=hz=0.125', 1.0),
}

LOOP_MODES = {'off': 'Kapalı', 'song': 'Şarkı', 'queue': 'Kuyruk'}


def video_id_from_url(url):
    """YouTube / YouTube Music linkinden video ID'si (bulunamazsa None)."""
    match = _VIDEO_ID_RE.search(url or "")
    return match.group(1) if match else None


def format_time(seconds):
    """90 -> '1:30', 3723 -> '1:02:03'."""
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def parse_time(text):
    """'1:30' / '90' / '1:02:03' -> saniye. Geçersizse ValueError."""
    parts = (text or "").strip().split(":")
    if len(parts) > 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"geçersiz süre: {text!r}")
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def parse_seek(text, current):
    """'1:30' mutlak konum; '+15' / '-1:00' çalan konuma göre ileri/geri."""
    text = (text or "").strip()
    if text.startswith(("+", "-")):
        delta = parse_time(text[1:])
        return max(0, current + delta if text[0] == "+" else current - delta)
    return parse_time(text)


def _seconds_or_none(text):
    try:
        return parse_time(text)
    except ValueError:
        return None


def song_thumbnail(song):
    """Şarkının kapak resmi (http/https); yoksa YouTube video ID'sinden türetilir."""
    thumbnail = song.get('thumbnail') or ''
    if thumbnail.startswith(('https://', 'http://')):
        return thumbnail
    video_id = video_id_from_url(song.get('webpage_url'))
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None


def _stream_url_expiring(url, margin=600):
    """googlevideo adresleri 'expire' parametresindeki zamanda (~6 saat) geçersizleşir."""
    try:
        expire = int(parse_qs(urlparse(url or '').query).get('expire', ['0'])[0])
    except ValueError:
        return False
    return expire > 0 and expire - time.time() < margin


def _probe_duration(path):
    """Yerel dosyanın süresi (sn); ffprobe yoksa ya da okuyamazsa None."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
            capture_output=True, text=True, timeout=10,
        )
        return int(float(result.stdout.strip()))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _wait_for_audio(source, timeout=10):
    """FFmpeg ilk sesi üretene kadar bekle (okumadan), kaynak değişince boşluk olmasın."""
    stdout = getattr(source, '_stdout', None)
    if stdout is None:
        return
    try:
        select.select([stdout], [], [], timeout)
    except (OSError, TypeError, ValueError):
        pass  # select pipe desteklemiyorsa (Windows) beklemeden devam


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
    MIN_LOOP_SECONDS = 3  # bundan kısa sürede biten şarkı çalınamamış sayılır, döngüye alınmaz
    MAX_CROSSFADE = 12  # sn
    MIN_CROSSFADE_SONG = 30  # bundan kısa şarkılarda geçiş yapılmaz
    PREFETCH_LEAD = 45  # geçişten bu kadar sn önce sıradakinin stream adresi alınır
    CROSSFADE_LEAD = 3  # geçişten bu kadar sn önce sıradakinin FFmpeg'i başlatılır
    WATCH_INTERVAL = 0.5

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
        self._autoplay_prep = None  # (seed şarkı, görev): geçiş için önceden aranan autoplay şarkısı
        self._epoch = 0  # stop/skip/cleanup/autoplay kapatma sırasında süren aramaları geçersiz kılar
        self._resolving_song = None  # stream adresi alınmakta olan şarkı
        self._start_task = None
        self.loop_mode = 'off'  # LOOP_MODES anahtarı
        self.filter = None  # AUDIO_FILTERS anahtarı
        self.card = None  # now_playing.NowPlayingCard; bot.py bağlar
        self.crossfade = 0  # şarkı geçişi süresi (sn), 0 = kapalı; bot.py ayarlar
        self._mixer = None  # çalan CrossfadeMixer
        self._prefetching = None  # stream adresi önceden alınan sıradaki şarkı
        self._tasks = set()
        self._skipping = False
        self._play_gen = 0  # her şarkı başlayınca artar: beklerken şarkı değişti mi
        self._play_offset = 0.0  # FFmpeg kaynağının şarkıda başladığı saniye
        self._play_started = None  # time.monotonic(); None = şarkı henüz çalmaya başlamadı
        self._paused_at = None

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)  # referans tutulmazsa görev yarıda çöpe gidebilir
        task.add_done_callback(self._tasks.discard)
        return task

    def _refresh_card(self):
        if self.card is not None:
            self.card.refresh()

    @property
    def is_loading(self):
        return self._resolving_song is not None

    def speed(self):
        """Filtrenin çalma hızı (nightcore 1.25, slowed 0.8)."""
        return AUDIO_FILTERS[self.filter][2] if self.filter else 1.0

    def position(self):
        """Çalan şarkıda kaçıncı saniyedeyiz (şarkının kendi zamanıyla)."""
        if self._play_started is None:
            return 0.0
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        return self._play_offset + (now - self._play_started) * self.speed()

    def _start_clock(self, offset):
        self._play_offset = offset
        self._play_started = time.monotonic()
        self._paused_at = self._play_started if self.is_paused else None

    def _stop_clock(self):
        self._play_started = None
        self._paused_at = None

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
        try:
            if hasattr(interaction, 'response') and not interaction.response.is_done():
                return await interaction.response.send_message(message, ephemeral=ephemeral)
            elif hasattr(interaction, 'followup'):
                return await interaction.followup.send(message, ephemeral=ephemeral)
            else:
                return await interaction.send(message)
        except discord.HTTPException as e:
            # Interaction token'ı 15 dk sonra geçersizleşir; mesaj gitmedi diye çalma durmasın
            print(f"⚠️ Mesaj gönderilemedi: {e}", flush=True)
            return None

    def _ensure_queue_id(self, song):
        song.setdefault("queue_id", uuid4().hex)
        return song["queue_id"]

    def reorder_queue(self, queue_ids: list[str]) -> None:
        current = list(self.queue)
        by_id = {self._ensure_queue_id(song): song for song in current}
        if len(by_id) != len(current) or len(queue_ids) != len(current) or set(queue_ids) != set(by_id):
            raise ValueError("invalid queue order")
        self.queue = deque(by_id[queue_id] for queue_id in queue_ids)
        self._refresh_card()

    def remove_from_queue(self, queue_id: str):
        """Kuyruktan queue_id ile şarkı çıkar. Returns removed song or None."""
        for index, song in enumerate(self.queue):
            if self._ensure_queue_id(song) == queue_id:
                del self.queue[index]
                self._refresh_card()
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
        self._refresh_card()
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
                "duration": s.get("duration") or None,
                "thumbnail": song_thumbnail(s),
            }
            if include_queue_id:
                result["queue_id"] = self._ensure_queue_id(s)
            return result
        current = song_dict(self.current)
        if current is not None:
            current["position"] = round(self.position(), 1)
            current["speed"] = self.speed()
        return {
            "current": current,
            "queue": [song_dict(s, include_queue_id=True) for s in list(self.queue)],
            "volume": self.get_volume(),
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "autoplay": self.autoplay,
            "loop": self.loop_mode,
            "filter": self.filter,
            "crossfade": self.crossfade,
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
            'duration': await asyncio.to_thread(_probe_duration, file_path),
        }
        self._ensure_queue_id(song)
        self.queue.append(song)
        self._refresh_card()

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
            'duration': stream_info.get('duration') or None,
            'thumbnail': stream_info.get('thumbnail') or '',
        }
        self._ensure_queue_id(song)
        self.queue.append(song)
        self._refresh_card()

        await self._send_message(interaction, f"✅ **{stream_info['title']}** kuyruğa eklendi! (🌐 Stream)")
        
        if not self.is_playing and not self.is_paused:
            await self.play_next(interaction)
        return True
    
    async def play_next(self, interaction):
        """Sıradaki şarkıyı çal. interaction may be None for web path."""
        if self.is_paused:
            return

        finished = self.current  # stop/cleanup sonrası None: o durumda autoplay devreye girmez
        self._requeue_for_loop(finished)
        self._stop_clock()
        if len(self.queue) == 0:
            self.is_playing = False
            self.current = None
            if self.autoplay and finished is not None and await self._autoplay_from(finished):
                return
            self._refresh_card()
            await self._send_message(interaction, "📭 Kuyruk boş!")
            return

        song = self.queue.popleft()
        self._set_current(song)

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
            self._refresh_card()  # kartta "hazırlanıyor" görünsün
            ready = await self._resolve_stream(song)
            if ready is None:
                return  # stop/skip/leave araya girdi
            if not ready:
                await self._send_message(interaction, f"⚠️ **{song['name']}** çalınamadı, sıradakine geçiyorum.")
                await self.play_next(interaction)
                return

        source = self._make_source(song)
        if not await self._warm_up(song, source):
            return  # stop/skip/leave araya girdi
        mixer = CrossfadeMixer(source, volume=self.volume)

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

        self._mixer = mixer
        self.voice_client.play(mixer, after=_after)
        if self.is_paused:  # stream adresi alınırken duraklatıldıysa
            self.voice_client.pause()
        self._song_started()

    def _set_current(self, song):
        self.current = song
        self.is_playing = True
        played_id = video_id_from_url(song.get('webpage_url'))
        if played_id:
            self.played_ids.append(played_id)

    def _song_started(self):
        """Ses başladı (play ya da geçiş): konum saati, kart ve şarkı sonu takibi."""
        self._play_gen += 1
        self._prefetching = None
        self._start_clock(0.0)
        self._refresh_card()
        if self.crossfade > 0:
            self._spawn(self._watch_song_end(self._play_gen))

    async def _warm_up(self, song, source):
        """FFmpeg ilk sesi verene kadar bekle; saat gerçek sesle başlasın, geçiş zamanı kaymasın.

        Returns False if stop/skip/leave happened meanwhile (source is cleaned up).
        """
        epoch = self._epoch
        self._resolving_song = song  # bu sırada skip gelirse bu şarkı bırakılır
        try:
            await asyncio.to_thread(_wait_for_audio, source)
        finally:
            if self._resolving_song is song:
                self._resolving_song = None
        if epoch != self._epoch or self.current is not song:
            source.cleanup()
            return False
        return True

    def _upcoming(self):
        """Çalan şarkı bitince çalacak şarkı (döngü dahil); kuyruğu değiştirmez."""
        if self.loop_mode == 'song' or (self.loop_mode == 'queue' and not self.queue):
            return self.current
        if self.queue:
            return self.queue[0]
        return self._prepared_autoplay_song() if self.autoplay else None

    @staticmethod
    def _ready(song):
        """Şarkı beklemeden başlatılabilir mi (stream adresi alınmış ve taze)."""
        if song is None:
            return False
        if not song.get('is_stream', False):
            return bool(song.get('file'))
        url = song.get('stream_url')
        return bool(url) and not _stream_url_expiring(url)

    def _remaining(self, duration):
        """Çalan şarkının bitmesine kalan gerçek süre (filtrenin hızı dahil)."""
        return (duration - self.position()) / self.speed()

    async def _watch_song_end(self, gen):
        """Şarkı bitmeye yaklaşınca sıradakini hazırla ve geçişi başlat.

        Sıradaki hazır değilse (stream adresi alınamadı vb.) geçiş yapılmaz; şarkı bitince
        play_next her zamanki gibi devam eder.
        """
        song = self.current
        while True:
            await asyncio.sleep(self.WATCH_INTERVAL)
            if self._play_gen != gen or self.current is not song or self.crossfade <= 0:
                return  # şarkı değişti, stop/leave ya da geçiş kapatıldı
            duration = song.get('duration')
            if not duration or duration < self.MIN_CROSSFADE_SONG:
                return  # süre bilinmiyor (canlı yayın) ya da şarkı çok kısa
            if self.is_paused:
                continue
            remaining = self._remaining(duration)
            if remaining <= self.crossfade + self.PREFETCH_LEAD:
                self._prefetch_upcoming()
            if remaining <= self.crossfade + self.CROSSFADE_LEAD and self._ready(self._upcoming()):
                await self._crossfade_to_next(gen, duration)
                return

    async def _crossfade_to_next(self, gen, duration):
        """Sıradaki şarkıyı aynı oynatıcıda başlat: çalan kısılırken o yükselir."""
        song, upcoming, mixer, vc = self.current, self._upcoming(), self._mixer, self.voice_client
        source = self._make_source(upcoming)
        await asyncio.to_thread(_wait_for_audio, source)

        def unchanged():
            return self._play_gen == gen and self.current is song

        # FFmpeg hazır; geçişin başlama anını bekle
        while unchanged() and (self.is_paused or self._remaining(duration) > self.crossfade):
            await asyncio.sleep(0.1)
        remaining = self._remaining(duration)
        if (not unchanged() or self._mixer is not mixer or self.voice_client is not vc
                or vc is None or not (vc.is_playing() or vc.is_paused())
                or self._upcoming() is not upcoming or remaining < 1):
            source.cleanup()  # bu sırada skip/stop/kuyruk değişikliği oldu ya da şarkı bitti
            return
        self._requeue_for_loop(self.current)
        if self.queue:
            self.queue.popleft()  # == upcoming
        else:
            self._autoplay_prep = None  # önceden bulunan autoplay şarkısı kullanıldı
        self._set_current(upcoming)
        mixer.crossfade(source, remaining)
        self._song_started()

    def _prefetch_upcoming(self):
        """Sıradaki şarkının stream adresini önceden al ki geçiş anında hazır olsun."""
        if not self.queue and self.loop_mode == 'off':
            self._prepare_autoplay()  # kuyruk bitiyor: sıradaki autoplay'den gelecek
            return
        song = self._upcoming()
        if (song is None or song is self._prefetching or self.downloader is None
                or not song.get('webpage_url') or not song.get('is_stream') or self._ready(song)):
            return
        self._prefetching = song  # başarısız olursa bu şarkı için tekrar deneme
        self._spawn(self._prefetch(song))

    async def _prefetch(self, song):
        try:
            info = await self.downloader.get_stream_url(song['webpage_url'])
        except Exception as e:
            print(f"⚠️ Sıradaki şarkı hazırlanamadı ({song['name']}): {e}", flush=True)
            return
        if info and not self._ready(song):
            self._apply_stream_info(song, info)

    def set_crossfade(self, seconds):
        """Şarkı geçişi süresi (sn); 0 = kapalı."""
        seconds = int(seconds)
        if not 0 <= seconds <= self.MAX_CROSSFADE:
            raise ValueError(f"crossfade must be 0-{self.MAX_CROSSFADE}")
        was_off = self.crossfade <= 0
        self.crossfade = seconds
        if seconds and was_off and self._play_started is not None:
            self._spawn(self._watch_song_end(self._play_gen))  # çalan şarkı için de

    def _make_source(self, song, position=0.0):
        """Şarkı için FFmpeg kaynağı: position saniyesinden başlar, seçili filtre uygulanır."""
        before = []
        if song.get('is_stream', False):
            before.append('-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5')
            path = song['stream_url']
        else:
            path = song['file']
        if position > 0:
            before.append(f'-ss {position:.2f}')
        options = '-vn'
        if self.filter:
            options += f' -af {AUDIO_FILTERS[self.filter][1]}'
        return discord.FFmpegPCMAudio(path, before_options=' '.join(before) or None, options=options)

    def _requeue_for_loop(self, finished):
        """Döngü açıksa biten şarkıyı kuyruğa geri koy (play_next başında çağrılır)."""
        skipped, self._skipping = self._skipping, False
        if finished is None or self.loop_mode == 'off':
            return
        # Hemen biten şarkı çalınamamıştır (bozuk adres vb.): döngüye alıp sonsuza dek deneme
        played = self._play_started is not None and self.position() >= self.MIN_LOOP_SECONDS
        if self.loop_mode == 'song' and played and not skipped:
            self.queue.appendleft(finished)
        elif self.loop_mode == 'queue' and (played or skipped):
            self.queue.append(finished)
        else:
            return
        if finished.get('webpage_url') and _stream_url_expiring(finished.get('stream_url')):
            finished['stream_url'] = None  # çalma sırası gelince yenisi alınır

    async def _restart_at(self, position):
        """Çalan şarkıyı position'dan (seçili filtreyle) yeniden başlat, sıradakine geçmeden.

        Mikserdeki kaynak değiştirilir; oynatıcı durmaz, after-callback tetiklenmez.
        """
        song, vc, mixer, gen = self.current, self.voice_client, self._mixer, self._play_gen
        if song is None or vc is None or mixer is None or self._play_started is None:
            return False
        source = self._make_source(song, position)
        await asyncio.to_thread(_wait_for_audio, source)
        if self._play_gen != gen or self.voice_client is not vc or not (vc.is_playing() or vc.is_paused()):
            source.cleanup()  # beklerken şarkı bitti ya da değişti
            return False
        mixer.replace(source)
        self._start_clock(position)
        self._refresh_card()
        return True

    async def seek(self, interaction, position):
        """Çalan şarkıda position saniyesine atla. Returns True on success."""
        if self.current is None or self._play_started is None:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!", ephemeral=True)
            return False
        duration = self.current.get('duration')
        if duration and position >= duration:
            await self._send_message(interaction, f"❌ Şarkı {format_time(duration)} uzunluğunda!", ephemeral=True)
            return False
        if not await self._restart_at(max(0, position)):
            await self._send_message(interaction, "❌ Atlanamadı, şarkı değişmiş olabilir.", ephemeral=True)
            return False
        await self._send_message(interaction, f"⏩ **{format_time(position)}** konumuna atlandı!")
        return True

    async def set_filter(self, interaction, name):
        """Ses filtresini değiştir (None = kapalı); çalan şarkıya kaldığı yerden uygulanır."""
        if name is not None and name not in AUDIO_FILTERS:
            raise ValueError(f"unknown filter: {name}")
        position = self.position()  # eski filtrenin hızıyla
        self.filter = name
        if self._play_started is not None:
            await self._restart_at(position)
        self._refresh_card()
        label = AUDIO_FILTERS[name][0] if name else "Kapalı"
        await self._send_message(interaction, f"🎛️ Filtre: **{label}**")

    def set_loop(self, mode):
        """Döngü modu: 'off', 'song' (şarkıyı tekrarla) ya da 'queue' (kuyruğu tekrarla)."""
        if mode not in LOOP_MODES:
            raise ValueError(f"unknown loop mode: {mode}")
        self.loop_mode = mode
        self._refresh_card()

    def cycle_loop(self):
        """kapalı -> şarkı -> kuyruk -> kapalı. Returns the new mode."""
        modes = list(LOOP_MODES)
        self.set_loop(modes[(modes.index(self.loop_mode) + 1) % len(modes)])
        return self.loop_mode

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
        self._apply_stream_info(song, info)
        return True

    @staticmethod
    def _apply_stream_info(song, info):
        song['stream_url'] = info['url']
        song['duration'] = info.get('duration') or song.get('duration')
        song['thumbnail'] = song.get('thumbnail') or info.get('thumbnail') or ''

    def enqueue_tracks(self, tracks, user):
        """Şarkıları stream adresini almadan kuyruğa ekle (adres çalma sırası gelince alınır).

        tracks: [{video_id, title, artists?, duration?, thumbnail?}]. Returns the queued song dicts.
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
                'duration': _seconds_or_none(t.get('duration')),  # YT Music: "3:45"
                'thumbnail': t.get('thumbnail') or '',
            }
            self._ensure_queue_id(song)
            self.queue.append(song)
            added.append(song)
        self._refresh_card()
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
            self._autoplay_prep = None
        self._refresh_card()

    def _next_autoplay_candidate(self):
        """Havuzdan daha önce çalınmamış ilk şarkıyı çıkar."""
        while self._autoplay_pool:
            candidate = self._autoplay_pool.pop(0)
            if candidate['id'] not in self.played_ids:
                return candidate
        return None

    async def _pick_autoplay_song(self, finished):
        """finished'a benzer, daha önce çalınmamış ve stream adresi alınmış şarkı (bulunamazsa None)."""
        seed = video_id_from_url(finished.get('webpage_url')) or (self.played_ids[-1] if self.played_ids else None)
        if seed is None:
            return None
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
        if not info:
            return None
        song = {
            'stream_url': info['url'],
            'name': info['title'],
            'user': AUTOPLAY_USER,
            'is_stream': True,
            'webpage_url': info.get('webpage_url', ''),
            'duration': info.get('duration') or None,
            'thumbnail': info.get('thumbnail') or '',
            'autoplay': True,
        }
        self._ensure_queue_id(song)
        return song

    def _prepare_autoplay(self):
        """Kuyruk boşken autoplay şarkısını çalan şarkı bitmeden bul, geçiş ona yapılabilsin.

        Şarkı kuyruğa konmaz: bu arada kullanıcı şarkı eklerse önce o çalar.
        """
        seed = self.current
        if (not self.autoplay or self.downloader is None or seed is None
                or (self._autoplay_prep is not None and self._autoplay_prep[0] is seed)):
            return
        self._autoplay_prep = (seed, self._spawn(self._pick_autoplay_song(seed)))

    def _prepared_autoplay_song(self):
        """Çalan şarkı için önceden bulunmuş autoplay şarkısı (hazır değilse None)."""
        prep = self._autoplay_prep
        if prep is None or prep[0] is not self.current or not prep[1].done() or prep[1].cancelled():
            return None
        return prep[1].result()

    async def _autoplay_from(self, finished):
        """Kuyruk bitince benzer bir şarkı ekleyip çal.

        Returns True if handled (a song was queued, or the user acted meanwhile),
        False if nothing could be found.
        """
        if self.downloader is None or self._autoplay_pending:
            return self._autoplay_pending

        epoch = self._epoch
        prep, self._autoplay_prep = self._autoplay_prep, None
        self._autoplay_pending = True
        try:
            if prep is not None and prep[0] is finished:
                song = await prep[1]  # geçiş için önceden arandı (bitmediyse sonucunu bekle)
            else:
                song = await self._pick_autoplay_song(finished)
        finally:
            self._autoplay_pending = False

        # Arama sürerken stop/leave/autoplay kapatma ya da yeni şarkı eklendiyse vazgeç
        if epoch != self._epoch or not self.autoplay or self.is_playing or self.queue:
            return True
        if song is None:
            return False
        self.queue.append(song)
        await self.play_next(None)
        return True

    async def skip(self, interaction):
        """Şarkıyı geç. Rely on voice after-callback to advance; only call play_next if no VC."""
        if not self.is_playing:
            await self._send_message(interaction, "❌ Şu anda hiçbir şarkı çalmıyor!")
            return

        self._skipping = True  # döngü: şarkı modunda geçilen şarkı tekrar çalınmasın
        # Duraklatılmışken geçilirse sıradaki çalsın; play_next duraklatılmışken bir şey yapmaz
        self.is_paused = False
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
        self._autoplay_prep = None
        self.queue.clear()
        if self.voice_client:
            self.voice_client.stop()
        
        self.is_playing = False
        self.is_paused = False
        self.current = None
        self._stop_clock()
        self._refresh_card()
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
        if self._play_started is not None:
            self._paused_at = time.monotonic()
        self._refresh_card()
        await self._send_message(interaction, "⏸️ Müzik duraklatıldı!")
    
    async def resume(self, interaction):
        """Müziği devam ettir"""
        if not self.is_paused:
            await self._send_message(interaction, "❌ Müzik duraklatılmamış!")
            return
        
        if self.voice_client:
            self.voice_client.resume()

        self.is_paused = False
        if self._paused_at is not None:
            self._play_started += time.monotonic() - self._paused_at
            self._paused_at = None
        self._refresh_card()
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
    
    def get_volume(self):
        """Mevcut ses seviyesini al"""
        return int(self.volume * 100)
    
    async def set_volume(self, interaction, volume):
        """Ses seviyesini ayarla"""
        self.volume = volume
        if self.voice_client and self.voice_client.source:
            self.voice_client.source.volume = volume
        self._refresh_card()

    async def clear_queue(self, interaction):
        """Kuyruğu temizle"""
        count = len(self.queue)
        self.queue.clear()
        self._refresh_card()
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
        self._refresh_card()
        await self._send_message(interaction, "🔀 Kuyruk karıştırıldı!")
    
    def cleanup(self):
        """Temizlik — stop playback and clear voice client reference."""
        self._epoch += 1  # süren autoplay aramasını iptal et
        self._autoplay_prep = None
        if self.voice_client:
            self.voice_client.stop()
        self.voice_client = None
        self.queue.clear()
        self.is_playing = False
        self.is_paused = False
        self.current = None
        self._stop_clock()
        self._refresh_card()
