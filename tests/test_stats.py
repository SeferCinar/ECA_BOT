"""Çalma istatistikleri: kayıt, özet sorguları, haftalık zamanlama ve embed."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from music import WebUser
from stats import PlayStats, build_stats_embed, format_duration, weekly_slot

IST = ZoneInfo("Europe/Istanbul")
T0 = datetime(2026, 10, 19, 12, 0, tzinfo=IST).timestamp()  # pazartesi öğlen


class Member:
    def __init__(self, id, name):
        self.id, self.name, self.display_name = id, name, name


ALI, AYSE = Member(11, "Ali"), Member(22, "Ayşe")


def song(vid, user, title=None, **extra):
    return {"name": title or f"Song {vid}", "user": user, "is_stream": True,
            "webpage_url": f"https://www.youtube.com/watch?v={vid}", "duration": 200, **extra}


def seeded():
    stats = PlayStats(":memory:")
    rows = [
        (song("aaaaaaaaaaa", ALI), 200, "ended", 0),
        (song("aaaaaaaaaaa", AYSE), 200, "ended", 3600),
        (song("aaaaaaaaaaa", ALI), 120, "stopped", 7200),        # 30 sn'den fazla: çalındı sayılır
        (song("bbbbbbbbbbb", AYSE), 200, "ended", 7300),
        (song("ccccccccccc", ALI), 5, "skipped", 7400),            # geçildi
        (song("ccccccccccc", AYSE), 8, "skipped", 7500),           # geçildi
        (song("ddddddddddd", WebUser("YT Music")), 200, "ended", 7600),
        (song("eeeeeeeeeee", WebUser("Autoplay"), autoplay=True), 200, "ended", 7700),
    ]
    for s, listened, reason, offset in rows:
        stats.record(1, s, listened, reason, now=T0 + offset)
    stats.record(2, song("zzzzzzzzzzz", ALI), 200, "ended", now=T0)  # başka sunucu
    return stats


def test_summary_counts_and_rankings():
    summary = seeded().summary(1, T0 - 1, T0 + 86400, IST)

    assert summary["plays"] == 6  # 2 geçilen hariç
    assert summary["listened"] == 200 * 5 + 120 + 5 + 8
    assert [(s["title"], s["count"]) for s in summary["top_songs"]][:2] == [("Song aaaaaaaaaaa", 3), ("Song eeeeeeeeeee", 1)]
    # Eşitlikte en son çalan önde; autoplay şarkıları kimseye yazılmaz
    assert summary["top_requesters"] == [
        {"id": 22, "name": "Ayşe", "count": 2},
        {"id": 11, "name": "Ali", "count": 2},
        {"id": 0, "name": "YT Music", "count": 1},
    ]
    assert summary["most_skipped"] == [{"title": "Song ccccccccccc", "count": 2}]
    assert summary["autoplay"] == 1
    assert summary["busiest_hour"] == 14  # 12:00'den 2 sa sonra yoğunlaşıyor


def test_summary_respects_period_and_guild():
    stats = seeded()
    assert stats.summary(1, T0 + 7000, T0 + 7350, IST)["plays"] == 2
    assert stats.summary(2, 0, T0 + 86400, IST)["plays"] == 1
    assert stats.summary(3, 0, T0 + 86400, IST)["plays"] == 0


def test_meta_round_trip():
    stats = PlayStats(":memory:")
    assert stats.get_meta("x") is None
    stats.set_meta("x", "1")
    stats.set_meta("x", "2")
    assert stats.get_meta("x") == "2"


def test_database_file_is_created(tmp_path):
    path = tmp_path / "nested" / "stats.db"
    PlayStats(str(path)).record(1, song("aaaaaaaaaaa", ALI), 10, "skipped")
    assert PlayStats(str(path)).summary(1, 0, 2e9, IST)["most_skipped"] == []  # tek geçiş listelenmez
    assert path.exists()


def test_weekly_slot_is_last_sunday_21():
    sunday_21 = datetime(2026, 10, 25, 21, 0, tzinfo=IST)
    assert weekly_slot(datetime(2026, 10, 25, 21, 0, tzinfo=IST)) == sunday_21
    assert weekly_slot(datetime(2026, 10, 26, 9, 30, tzinfo=IST)) == sunday_21
    assert weekly_slot(datetime(2026, 11, 1, 20, 59, tzinfo=IST)) == sunday_21
    assert weekly_slot(datetime(2026, 10, 25, 20, 0, tzinfo=IST)) == sunday_21 - timedelta(days=7)


def test_format_duration():
    assert format_duration(59) == "0 dk"
    assert format_duration(3725) == "1 sa 2 dk"


def test_embed_lists_people_and_songs():
    embed = build_stats_embed(seeded().summary(1, T0 - 1, T0 + 86400, IST), "📊 Son 7 gün")
    fields = {f.name: f.value for f in embed.fields}

    assert "**6** şarkı" in embed.description
    assert fields["🔥 En çok çalınanlar"].startswith("🥇 [Song aaaaaaaaaaa](https://www.youtube.com/watch?v=aaaaaaaaaaa) — 3×")
    assert "<@11>" in fields["🙋 En çok şarkı açanlar"]
    assert "YT Music" in fields["🙋 En çok şarkı açanlar"]
    assert "Song ccccccccccc — 2 kez" in fields["⏭️ En çok geçilenler"]
    assert "14:00" in fields["✨ Ayrıca"]


def test_embed_for_empty_period():
    embed = build_stats_embed(PlayStats(":memory:").summary(1, 0, 1, IST), "📊")
    assert "hiç şarkı çalınmadı" in embed.description
    assert not embed.fields


def test_titles_with_markdown_are_escaped():
    stats = PlayStats(":memory:")
    stats.record(1, song("aaaaaaaaaaa", ALI, title="**bold** _x_"), 200, "ended", now=T0)
    embed = build_stats_embed(stats.summary(1, 0, T0 + 1, IST), "t")
    assert "\\*\\*bold\\*\\*" in embed.fields[0].value


def test_utc_timezone_also_works():
    summary = seeded().summary(1, T0 - 1, T0 + 86400, timezone.utc)
    assert summary["busiest_hour"] == 11
