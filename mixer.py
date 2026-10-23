"""Şarkılar arası geçiş (crossfade) yapan ses kaynağı.

discord.py aynı anda tek kaynak çalar. Bu kaynak çalan şarkıyı okur; geçiş başlayınca
sıradaki şarkının kaynağını da okuyup ikisini karıştırır: eski şarkı kısılırken yenisi
yükselir. Oynatıcı hiç durmadığı için şarkılar arasında boşluk olmaz.
"""
import audioop
import threading

import discord

FRAME_SIZE = discord.opus.Encoder.FRAME_SIZE  # 20 ms, 48 kHz stereo s16le
FRAMES_PER_SECOND = 50
SILENCE = b"\x00" * FRAME_SIZE


def _smoothstep(t):
    """0..1 arası yumuşak eğri: geçişin başı ve sonu sert olmasın."""
    return t * t * (3 - 2 * t)


class CrossfadeMixer(discord.AudioSource):
    """Çalan şarkının kaynağı ve geçişte kısılan önceki şarkı.

    Ses seviyesini de uygular (PCMVolumeTransformer yerine): voice_client.source.volume
    değişince hemen etkiler. Kazançların toplamı hep 1 olduğu için karışım taşmaz.
    """

    def __init__(self, source, volume=1.0):
        self.volume = volume
        self._source = source  # çalan şarkı (geçişte yükselen)
        self._outgoing = None  # geçişte kısılan önceki şarkı
        self._step = 0
        self._steps = 0
        self._lock = threading.Lock()  # read() oynatıcı thread'inde, diğerleri event loop'ta

    def is_opus(self):
        return False

    def read(self):
        with self._lock:
            data = self._source.read()
            if self._outgoing is not None:
                data = self._mix(data)
        if not data:
            return b""
        return audioop.mul(data, 2, min(max(self.volume, 0.0), 2.0))

    def _mix(self, incoming):
        outgoing = self._outgoing.read()
        self._step += 1
        gain = _smoothstep(min(1.0, self._step / self._steps))
        if self._step >= self._steps:
            self._outgoing.cleanup()
            self._outgoing = None
        if not incoming and not outgoing:
            return b""
        # Biri erken biterse (süre bilgisi kayık, bozuk stream) sessizlik sayılır; eğri bozulmaz
        return audioop.add(
            audioop.mul(outgoing or SILENCE, 2, 1.0 - gain),
            audioop.mul(incoming or SILENCE, 2, gain),
            2,
        )

    def crossfade(self, source, seconds):
        """source'a geçiş başlat: seconds boyunca çalan kısılır, source yükselir."""
        with self._lock:
            if self._outgoing is not None:
                self._outgoing.cleanup()  # önceki geçiş bitmeden yenisi geldi
            self._outgoing, self._source = self._source, source
            self._step, self._steps = 0, max(1, int(seconds * FRAMES_PER_SECOND))

    def replace(self, source):
        """Çalan şarkının kaynağını değiştir (seek/filtre); süren geçiş varsa hemen biter."""
        with self._lock:
            old = (self._source, self._outgoing)
            self._source, self._outgoing = source, None
        for s in old:
            if s is not None:
                s.cleanup()

    def cleanup(self):
        with self._lock:
            sources = (self._source, self._outgoing)
            self._outgoing = None
        for s in sources:
            if s is not None:
                s.cleanup()
