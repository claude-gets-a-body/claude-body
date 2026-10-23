"""Nightly memory job: turn yesterday into a diary page and updated memory files.

After a conversation day ends (04:00 Perth) and the clock passes `nightly_after`
(04:15 by default), the day's transcript and the current memory files go to
Claude as ONE request through the Message Batches API, which is half price and
fine for something nobody is waiting on. Batches usually finish within an hour
(at most 24 h). The job is tracked in SQLite, so a restart just carries on
polling.

Claude answers in a fixed JSON shape (structured outputs):
    {"diary": "...markdown...",
     "file_updates": [{"path": "/memories/people/sam.md", "content": "...full file..."}]}

Only a short list of paths may be written (see ALLOWED_PATH), and every write
goes through MemoryStore, which checks the path and keeps a backup of the old
file in .history/.

It also applies the RETENTION policy once a day: conversation logs in
state/days/ and transcript rows older than `retention_days` (default 30) are
deleted, along with old fired timers. (Memory files and the diary are kept:
they're the robot's memory, and Nick can edit or delete them.)

The batch request has no `fallbacks` (the Batches API doesn't accept it) and no
forced tool_choice (Opus 5.5 rejects it).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from common.clock import PERTH, Clock, day_key, parse_hhmm

from .budget import BudgetGovernor
from .config import MindConfig
from .memory_tool import MemoryStore
from .transcripts import TranscriptStore

log = logging.getLogger(__name__)

ALLOWED_PATH = re.compile(r"^/memories/((INDEX|me|house|promises)\.md|people/[a-z0-9_-]+\.md)$")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "diary": {"type": "string"},
        "file_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["diary", "file_updates"],
    "additionalProperties": False,
}


class NightlyJob:
    def __init__(self, cfg: MindConfig, llm, memory: MemoryStore, transcripts: TranscriptStore,
                 budget: BudgetGovernor, clock: Clock, prompt_text: str):
        self.cfg = cfg
        self.llm = llm
        self.memory = memory
        self.transcripts = transcripts
        self.budget = budget
        self.clock = clock
        self.prompt_text = prompt_text
        self.db = sqlite3.connect(str(cfg.db_path), check_same_thread=False)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS nightly_jobs (
                day TEXT PRIMARY KEY,
                batch_id TEXT,
                status TEXT NOT NULL,      -- submitted / done / failed
                detail TEXT,
                updated TEXT
            )""")
        self.db.commit()
        self._last_prune: date | None = None

    # ------------------------------------------------------------- retention
    def prune(self, today: date) -> dict:
        """Delete logs and transcripts older than retention_days. Returns counts."""
        cutoff = today - timedelta(days=self.cfg.retention_days)
        removed_files = 0
        days_dir = Path(self.cfg.state_dir) / "days"
        if days_dir.is_dir():
            for f in days_dir.iterdir():
                m = re.match(r"^(\d{4}-\d{2}-\d{2})\.", f.name)
                if m and date.fromisoformat(m.group(1)) < cutoff:
                    f.unlink()
                    removed_files += 1
        rows = self.transcripts.prune_before(cutoff)
        try:
            self.db.execute("DELETE FROM timers WHERE fired = 1 AND due < ?", (cutoff.isoformat(),))
            self.db.commit()
        except sqlite3.OperationalError:
            pass   # no timers table yet
        self._last_prune = today
        if removed_files or rows:
            log.info("retention: removed %d log file(s) and %d transcript line(s) older than %s",
                     removed_files, rows, cutoff)
        return {"files": removed_files, "transcript_rows": rows}

    def prune_if_due(self) -> None:
        today = day_key(self.clock.now(), self.cfg.day_starts_at)
        if self._last_prune != today:
            self.prune(today)

    # ---------------------------------------------------------------- state
    def _job(self, day: date):
        return self.db.execute("SELECT batch_id, status FROM nightly_jobs WHERE day = ?",
                               (day.isoformat(),)).fetchone()

    def _set(self, day: date, status: str, batch_id: str | None = None, detail: str = "") -> None:
        self.db.execute(
            "INSERT INTO nightly_jobs (day, batch_id, status, detail, updated) VALUES (?,?,?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET status=excluded.status, detail=excluded.detail, "
            "updated=excluded.updated, batch_id=COALESCE(excluded.batch_id, nightly_jobs.batch_id)",
            (day.isoformat(), batch_id, status, detail, self.clock.now().isoformat()))
        self.db.commit()

    def days_ready(self) -> list[date]:
        """Finished days with something in the transcript and no job yet."""
        now = self.clock.now()
        today = day_key(now, self.cfg.day_starts_at)
        after = parse_hhmm(self.cfg.nightly_after)
        ready = []
        for d in self.transcripts.days_with_activity():
            if d >= today or self._job(d):
                continue
            run_from = datetime.combine(d + timedelta(days=1), after, tzinfo=PERTH)
            if now >= run_from:
                ready.append(d)
        return ready

    # --------------------------------------------------------------- request
    def _memory_snapshot(self) -> str:
        parts = []
        for path in ["/memories/INDEX.md", "/memories/me.md", "/memories/house.md", "/memories/promises.md"]:
            parts.append(f"### {path}\n{self.memory.read_text(path, '(missing)')}")
        people = self.memory.resolve("/memories/people")
        if people.is_dir():
            for f in sorted(people.glob("*.md")):
                parts.append(f"### /memories/people/{f.name}\n{f.read_text(encoding='utf-8')}")
        return "\n\n".join(parts)

    def build_request(self, day: date) -> dict:
        user_text = (f"Day: {day:%A %d %B %Y}\n\n## Transcript\n{self.transcripts.day_text(day)}\n\n"
                     f"## Current memory files\n{self._memory_snapshot()}")
        return {
            "custom_id": f"diary-{day.isoformat()}",
            "params": {
                "model": self.cfg.claude.model,
                "max_tokens": self.cfg.claude.nightly_max_tokens,
                "system": self.prompt_text,
                "messages": [{"role": "user", "content": user_text}],
                "output_config": {"effort": self.cfg.claude.effort_task,
                                  "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            },
        }

    # ----------------------------------------------------------------- steps
    async def submit_ready(self) -> list[date]:
        submitted = []
        for d in self.days_ready():
            if self.budget.status().level == "over":
                log.warning("monthly cap reached; not submitting the diary job for %s", d)
                break
            batch_id = await self.llm.create_batch([self.build_request(d)])
            self._set(d, "submitted", batch_id)
            log.info("submitted diary batch %s for %s", batch_id, d)
            submitted.append(d)
        return submitted

    async def collect_finished(self) -> list[date]:
        rows = self.db.execute("SELECT day, batch_id FROM nightly_jobs WHERE status = 'submitted'").fetchall()
        finished = []
        for day_text, batch_id in rows:
            d = date.fromisoformat(day_text)
            if not await self.llm.batch_ended(batch_id):
                continue
            try:
                results = await self.llm.batch_results(batch_id)
                self._apply(d, results)
                self._set(d, "done")
                finished.append(d)
            except Exception as e:
                log.exception("diary job for %s failed", d)
                self._set(d, "failed", detail=f"{type(e).__name__}: {e}")
        return finished

    def _apply(self, day: date, results: list) -> None:
        for r in results:
            if r.custom_id != f"diary-{day.isoformat()}":
                continue
            if r.result.type != "succeeded":
                raise RuntimeError(f"batch item {r.result.type}")
            message = r.result.message
            if getattr(self.llm, "on_plan", False):     # claude_code brain: plan usage, logged not counted
                self.budget.record_plan(message.usage.to_dict(), message.model, getattr(r, "notional_usd", 0.0))
            else:
                self.budget.record(message.usage, message.model, kind="batch")
            if message.stop_reason == "refusal":
                raise RuntimeError("diary request was refused")
            text = next(b.text for b in message.content if b.type == "text")
            data = json.loads(text)

            self.memory.write_text(f"/memories/diary/{day.isoformat()}.md", data["diary"].rstrip() + "\n")
            for update in data.get("file_updates", []):
                path = update.get("path", "")
                if not ALLOWED_PATH.match(path):
                    log.warning("nightly job tried to write %r; skipped", path)
                    continue
                self.memory.write_text(path, update["content"].rstrip() + "\n")
            log.info("diary for %s written, %d memory file(s) updated", day, len(data.get("file_updates", [])))
            return
        raise RuntimeError("no result for this day in the batch")

    async def run(self) -> None:
        while True:
            try:
                self.prune_if_due()
                await self.submit_ready()
                await self.collect_finished()
            except Exception:
                log.exception("nightly job tick failed")
            await asyncio.sleep(self.cfg.nightly_poll_s)
