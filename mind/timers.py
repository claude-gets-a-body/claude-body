"""`timer(minutes, note)` — remind someone later.

Timers are kept in SQLite so a restart of the mind doesn't lose them. When one
comes due, `due()` hands it to the engine, which starts a Claude turn with
"[timer] ..." so Claude can go and say it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from common.clock import PERTH

MAX_MINUTES = 24 * 60


class Timers:
    def __init__(self, db_path: Path | str, now):
        self.now = now
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS timers (
                id INTEGER PRIMARY KEY,
                due TEXT NOT NULL,         -- ISO time, Perth
                note TEXT NOT NULL,
                for_person TEXT,
                fired INTEGER NOT NULL DEFAULT 0
            )""")
        self.db.commit()

    def add(self, minutes: float, note: str, for_person: str | None = None) -> str:
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            return "Error: minutes must be a number."
        if not 0 < minutes <= MAX_MINUTES:
            return f"Error: minutes must be between 0 and {MAX_MINUTES}."
        due = self.now() + timedelta(minutes=minutes)
        self.db.execute("INSERT INTO timers (due, note, for_person) VALUES (?, ?, ?)",
                        (due.isoformat(), note, for_person))
        self.db.commit()
        local = due.astimezone(PERTH)
        return f"Timer set for {local:%H:%M} ({minutes:g} min): {note}"

    def due(self) -> list[dict]:
        """Timers that are due now. Each is returned once, then marked fired."""
        now = self.now()
        rows = self.db.execute("SELECT id, due, note, for_person FROM timers WHERE fired = 0").fetchall()
        ready = [r for r in rows if datetime.fromisoformat(r[1]) <= now]
        for r in ready:
            self.db.execute("UPDATE timers SET fired = 1 WHERE id = ?", (r[0],))
        self.db.commit()
        return [{"id": r[0], "due": r[1], "note": r[2], "for_person": r[3]} for r in ready]

    def pending(self) -> list[dict]:
        rows = self.db.execute("SELECT id, due, note, for_person FROM timers WHERE fired = 0 ORDER BY due").fetchall()
        return [{"id": r[0], "due": r[1], "note": r[2], "for_person": r[3]} for r in rows]
