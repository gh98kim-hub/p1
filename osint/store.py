"""신호 저장소(SQLite). 처음 본 신호 판별, 모자이크용 최근 신호 조회, 채널별 마지막 수집 시각."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  uid TEXT PRIMARY KEY, channel TEXT, title TEXT, url TEXT, published TEXT, source TEXT,
  text TEXT, lang TEXT, query TEXT, meta TEXT, entities TEXT, locations TEXT, first_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_first_seen ON signals(first_seen);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


def _iso(dt):
    return dt.isoformat() if dt else None


def _dt(s):
    return datetime.fromisoformat(s) if s else None


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    def upsert(self, signals, now=None):
        """새 신호는 저장하고 is_new=True, 이미 본 신호는 first_seen을 되살리고 is_new=False."""
        now = now or datetime.now(timezone.utc)
        for s in signals:
            row = self.db.execute("SELECT first_seen FROM signals WHERE uid=?", (s.uid,)).fetchone()
            if row:
                s.is_new, s.first_seen = False, _dt(row[0])
                self.db.execute("UPDATE signals SET entities=?, locations=? WHERE uid=?",
                                (json.dumps(s.entities, ensure_ascii=False),
                                 json.dumps(s.locations, ensure_ascii=False), s.uid))
                continue
            s.is_new, s.first_seen = True, now
            self.db.execute(
                "INSERT INTO signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (s.uid, s.channel, s.title, s.url, _iso(s.published), s.source, s.text, s.lang, s.query,
                 json.dumps(s.meta, ensure_ascii=False), json.dumps(s.entities, ensure_ascii=False),
                 json.dumps(s.locations, ensure_ascii=False), _iso(now)))
        self.db.commit()

    def recent(self, days, now=None):
        now = now or datetime.now(timezone.utc)
        cut = _iso(now - timedelta(days=days))
        rows = self.db.execute("SELECT * FROM signals WHERE first_seen >= ? OR published >= ?", (cut, cut))
        out = []
        for r in rows.fetchall():
            out.append(Signal(channel=r[1], title=r[2], url=r[3], published=_dt(r[4]), source=r[5], text=r[6],
                              lang=r[7], query=r[8], meta=json.loads(r[9] or "{}"),
                              entities=json.loads(r[10] or "[]"), locations=json.loads(r[11] or "[]"),
                              first_seen=_dt(r[12]), is_new=False))
        return out

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, str(value)))
        self.db.commit()
