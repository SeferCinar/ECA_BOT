"""Çalma istatistikleri: her şarkı bitince SQLite'a bir satır; /stats ve haftalık özet buradan.

Tek bir dosya (data/stats.db), ayrı veritabanı sunucusu gerekmez. Şarkı başına bir INSERT.
"""
import os
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

import discord

from music import video_id_from_url

SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    ended_at REAL NOT NULL,          -- unix zamanı
    song_key TEXT NOT NULL,          -- YouTube video ID'si ya da dosya adı
    title TEXT NOT NULL,
    webpage_url TEXT,
    requester_id INTEGER NOT NULL,   -- web paneli / autoplay için 0
    requester_name TEXT NOT NULL,
    is_autoplay INTEGER NOT NULL,
    listened REAL NOT NULL,          -- dinlenen sn (şarkının kendi zamanıyla)
    duration REAL,
    reason TEXT NOT NULL             -- ended / skipped / stopped / back
);
CREATE INDEX IF NOT EXISTS plays_guild_time ON plays (guild_id, ended_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

MIN_PLAY_SECONDS = 30  # sonuna kadar çalmayan şarkı en az bu kadar dinlendiyse "çalındı" sayılır
WEEKLY_WEEKDAY = 6  # pazar
WEEKLY_HOUR = 21

PLAYED = f"(reason = 'ended' OR listened >= {MIN_PLAY_SECONDS})"
SKIPPED = f"(reason = 'skipped' AND listened < {MIN_PLAY_SECONDS})"
# Discord kullanıcıları ID ile, web paneli / eklenti adla gruplanır
REQUESTER = "CASE WHEN requester_id != 0 THEN CAST(requester_id AS TEXT) ELSE requester_name END"


class PlayStats:
    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()  # /stats sorgusu thread'de, kayıtlar event loop'ta

    def record(self, guild_id, song, listened, reason, now=None):
        user = song.get("user")
        name = getattr(user, "display_name", None) or getattr(user, "name", None) or str(user)
        key = video_id_from_url(song.get("webpage_url")) or song.get("file") or song.get("name") or "?"
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO plays (guild_id, ended_at, song_key, title, webpage_url, requester_id,"
                " requester_name, is_autoplay, listened, duration, reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id, now if now is not None else time.time(), key, song.get("name") or key,
                    song.get("webpage_url") or None, getattr(user, "id", 0) or 0, name,
                    int(bool(song.get("autoplay"))), round(float(listened), 1), song.get("duration"), reason,
                ),
            )

    def get_meta(self, key):
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key, value):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    def summary(self, guild_id, since, until, tz):
        """since..until (unix) arası özet. tz: en yoğun saati yerel saatle vermek için."""
        where = "guild_id = ? AND ended_at >= ? AND ended_at < ?"
        args = (guild_id, since, until)
        with self._lock:
            q = self._db.execute
            plays, listened = q(
                f"SELECT COALESCE(SUM({PLAYED}), 0), COALESCE(SUM(listened), 0) FROM plays WHERE {where}",
                args,
            ).fetchone()
            top_songs = q(
                f"SELECT title, webpage_url, COUNT(*) AS c, MAX(ended_at) FROM plays"
                f" WHERE {where} AND {PLAYED} GROUP BY song_key ORDER BY c DESC, MAX(ended_at) DESC LIMIT 5",
                args,
            ).fetchall()
            top_requesters = q(
                f"SELECT requester_id, requester_name, COUNT(*) AS c, MAX(ended_at) FROM plays"
                f" WHERE {where} AND {PLAYED} AND is_autoplay = 0"
                f" GROUP BY {REQUESTER} ORDER BY c DESC, MAX(ended_at) DESC LIMIT 5",
                args,
            ).fetchall()
            most_skipped = q(
                f"SELECT title, COUNT(*) AS c, MAX(ended_at) FROM plays"
                f" WHERE {where} AND {SKIPPED} GROUP BY song_key HAVING c >= 2"
                f" ORDER BY c DESC, MAX(ended_at) DESC LIMIT 3",
                args,
            ).fetchall()
            autoplay = q(f"SELECT COUNT(*) FROM plays WHERE {where} AND {PLAYED} AND is_autoplay = 1", args).fetchone()[0]
            times = [row[0] for row in q(f"SELECT ended_at FROM plays WHERE {where} AND {PLAYED}", args)]
        hours = Counter(datetime.fromtimestamp(t, tz).hour for t in times)
        return {
            "plays": plays,
            "listened": listened,
            "top_songs": [{"title": t, "url": u, "count": c} for t, u, c, _ in top_songs],
            "top_requesters": [{"id": i, "name": n, "count": c} for i, n, c, _ in top_requesters],
            "most_skipped": [{"title": t, "count": c} for t, c, _ in most_skipped],
            "autoplay": autoplay,
            "busiest_hour": hours.most_common(1)[0][0] if hours else None,
        }


def weekly_slot(now):
    """now'dan önceki son haftalık özet zamanı (pazar 21:00, now'un saat diliminde)."""
    slot = now.replace(hour=WEEKLY_HOUR, minute=0, second=0, microsecond=0)
    slot -= timedelta(days=(now.weekday() - WEEKLY_WEEKDAY) % 7)
    return slot if slot <= now else slot - timedelta(days=7)


def format_duration(seconds):
    """3725 -> '1 sa 2 dk'."""
    minutes = int(seconds) // 60
    hours, minutes = divmod(minutes, 60)
    return f"{hours} sa {minutes} dk" if hours else f"{minutes} dk"


def _escape(text, limit=80):
    text = str(text or "")
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    return discord.utils.escape_markdown(text)


def _song_link(song):
    title = _escape(song["title"])
    return f"[{title}]({song['url']})" if song["url"] else title


def _person(requester):
    """Discord kullanıcısı etiketlenir (bildirim gitmez), web paneli/eklenti adıyla yazılır."""
    return f"<@{requester['id']}>" if requester["id"] else _escape(requester["name"])


def build_stats_embed(summary, title):
    if not summary["plays"]:
        return discord.Embed(title=title, description="Bu dönemde hiç şarkı çalınmadı. 🤫", color=discord.Color.dark_grey())

    embed = discord.Embed(
        title=title,
        description=f"🎵 **{summary['plays']}** şarkı · 🎧 **{format_duration(summary['listened'])}** dinleme",
        color=discord.Color.blurple(),
    )
    medals = ["🥇", "🥈", "🥉", "4.", "5."]
    songs = [f"{medal} {_song_link(s)} — {s['count']}×" for medal, s in zip(medals, summary["top_songs"])]
    embed.add_field(name="🔥 En çok çalınanlar", value="\n".join(songs), inline=False)
    if summary["top_requesters"]:
        people = [
            f"{medal} {_person(r)} — {r['count']} şarkı" for medal, r in zip(medals, summary["top_requesters"])
        ]
        embed.add_field(name="🙋 En çok şarkı açanlar", value="\n".join(people), inline=False)
    if summary["most_skipped"]:
        skipped = [f"• {_escape(s['title'])} — {s['count']} kez" for s in summary["most_skipped"]]
        embed.add_field(name="⏭️ En çok geçilenler", value="\n".join(skipped), inline=False)
    extras = []
    if summary["busiest_hour"] is not None:
        extras.append(f"⏰ En yoğun saat: **{summary['busiest_hour']:02d}:00**")
    if summary["autoplay"]:
        extras.append(f"📻 Autoplay **{summary['autoplay']}** şarkı seçti")
    if extras:
        embed.add_field(name="✨ Ayrıca", value="\n".join(extras), inline=False)
    return embed

