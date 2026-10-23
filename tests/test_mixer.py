"""CrossfadeMixer: PCM karıştırma, ses seviyesi, geçişin bitişi ve temizlik."""
import struct

from mixer import FRAME_SIZE, CrossfadeMixer


class Tone:
    """Sabit genlikli PCM kareleri veren sahte kaynak (frames: kaç kare sonra biter)."""

    def __init__(self, level, frames=None):
        self.frame = struct.pack("<h", level) * (FRAME_SIZE // 2)
        self.left = frames
        self.cleaned = False

    def read(self):
        if self.left is not None:
            if self.left <= 0:
                return b""
            self.left -= 1
        return self.frame

    def cleanup(self):
        self.cleaned = True


def level(data):
    samples = struct.unpack(f"<{len(data) // 2}h", data)
    assert len(set(samples)) == 1
    return samples[0]


def test_applies_volume():
    mixer = CrossfadeMixer(Tone(10000), volume=0.5)
    assert level(mixer.read()) == 5000
    mixer.volume = 1.5
    assert level(mixer.read()) == 15000


def test_crossfade_ramps_from_old_to_new_then_drops_old():
    old, new = Tone(10000), Tone(20000)
    mixer = CrossfadeMixer(old)
    mixer.crossfade(new, 0.1)  # 5 kare

    levels = [level(mixer.read()) for _ in range(5)]

    assert levels == sorted(levels) and 10000 < levels[0] < levels[2] < 20000
    assert levels[-1] == 20000
    assert old.cleaned and mixer._outgoing is None
    assert level(mixer.read()) == 20000


def test_crossfade_never_clips():
    """Gains always sum to 1, so two loud songs never exceed full scale."""
    mixer = CrossfadeMixer(Tone(32000))
    mixer.crossfade(Tone(32000), 1)
    assert all(abs(level(mixer.read()) - 32000) <= 2 for _ in range(50))


def test_old_song_ending_early_counts_as_silence():
    mixer = CrossfadeMixer(Tone(10000, frames=1))
    mixer.crossfade(Tone(20000), 0.1)

    levels = [level(mixer.read()) for _ in range(5)]

    assert levels[1] < levels[2] < levels[3] < levels[4] == 20000  # yeni şarkı yükselmeye devam eder
    assert levels[1] < 10000


def test_ends_when_every_source_ends():
    mixer = CrossfadeMixer(Tone(10000, frames=1))
    mixer.crossfade(Tone(20000, frames=0), 1)
    assert mixer.read() != b""
    assert mixer.read() == b""

    assert CrossfadeMixer(Tone(1, frames=0)).read() == b""


def test_replace_finishes_the_fade():
    old, current, new = Tone(10000), Tone(20000), Tone(30000)
    mixer = CrossfadeMixer(old)
    mixer.crossfade(current, 1)
    mixer.read()

    mixer.replace(new)

    assert old.cleaned and current.cleaned
    assert level(mixer.read()) == 30000


def test_cleanup_closes_both_sources():
    old, new = Tone(1), Tone(2)
    mixer = CrossfadeMixer(old)
    mixer.crossfade(new, 1)
    mixer.cleanup()
    assert old.cleaned and new.cleaned
