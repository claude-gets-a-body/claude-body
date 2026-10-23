"""Transcript store: everything heard and said, searchable with SQLite FTS5.

`recall(query)` is Claude's way to look further back than today's conversation
("what did Sam say about the excursion last week?"). The nightly job also reads a
whole day from here to write the diary.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime
from pathlib import Path


class TranscriptStore:
    def __init__(self, db_path: Path | str):
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS utterances (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,          -- ISO time, Perth
                day TEXT NOT NULL,         -- conversation day, YYYY-MM-DD
                who TEXT NOT NULL,         -- a person's name, 'someone', 'claude', or 'event'
                text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS utterances_day ON utterances(day);
            CREATE VIRTUAL TABLE IF NOT EXISTS utterances_fts USING fts5(
                text, who, content='utterances', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS utterances_ai AFTER INSERT ON utterances BEGIN
                INSERT INTO utterances_fts(rowid, text, who) VALUES (new.id, new.text, new.who);
            END;
            CREATE TRIGGER IF NOT EXISTS utterances_ad AFTER DELETE ON utterances BEGIN
                INSERT INTO utterances_fts(utterances_fts, rowid, text, who)
                VALUES ('delete', old.id, old.text, old.who);
            END;
        """)
        self.db.commit()

    def add(self, when: datetime, day: date, who: str, text: str) -> None:
        self.db.execute("INSERT INTO utterances (ts, day, who, text) VALUES (?, ?, ?, ?)",
                        (when.isoformat(timespec="seconds"), day.isoformat(), who, text))
        self.db.commit()

    @staticmethod
    def _fts_query(query: str) -> str:
        """Turn free text into a safe FTS5 query: each word quoted, OR-ed together.
        (Raw user text can contain FTS syntax like quotes or NEAR that would error.)"""
        words = re.findall(r"\w+", query.lower())
        words = [w for w in words if len(w) > 1][:12]
        return " OR ".join(f'"{w}"' for w in words)

    def search(self, query: str, limit: int = 10, before_day: date | None = None) -> list[dict]:
        fts = self._fts_query(query)
        if not fts:
            return []
        sql = ("SELECT u.ts, u.day, u.who, u.text FROM utterances_fts f "
               "JOIN utterances u ON u.id = f.rowid WHERE utterances_fts MATCH ?")
        args: list = [fts]
        if before_day is not None:
            sql += " AND u.day < ?"
            args.append(before_day.isoformat())
        sql += " ORDER BY bm25(utterances_fts) LIMIT ?"
        args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        return [{"ts": ts, "day": d, "who": who, "text": text} for ts, d, who, text in rows]

    def recall(self, query: str, limit: int = 10) -> str:
        """Text answer for the `recall` tool."""
        hits = self.search(query, limit=limit)
        if not hits:
            return f"Nothing found in old transcripts for {query!r}."
        lines = [f"{len(hits)} match(es), best first:"]
        for h in hits:
            lines.append(f"- {h['ts'][:16].replace('T', ' ')}  {h['who']}: {h['text']}")
        return "\n".join(lines)

    def day_text(self, day: date) -> str:
        """The whole of one day, in order, for the nightly diary job."""
        rows = self.db.execute("SELECT ts, who, text FROM utterances WHERE day = ? ORDER BY id",
                               (day.isoformat(),)).fetchall()
        return "\n".join(f"{ts[11:16]} {who}: {text}" for ts, who, text in rows)

    def excerpt(self, day: date, max_lines: int = 80, max_chars: int = 8000) -> str:
        """The most recent part of a day, as plain text (seeds a restarted segment)."""
        lines = self.day_text(day).splitlines()[-max_lines:]
        text = "\n".join(lines)
        return text[-max_chars:]

    def prune_before(self, day: date) -> int:
        """Retention: delete everything from days before `day`. Returns rows removed."""
        cur = self.db.execute("DELETE FROM utterances WHERE day < ?", (day.isoformat(),))
        self.db.commit()
        return cur.rowcount

    def days_with_activity(self) -> list[date]:
        rows = self.db.execute("SELECT DISTINCT day FROM utterances ORDER BY day").fetchall()
        return [date.fromisoformat(r[0]) for r in rows]
