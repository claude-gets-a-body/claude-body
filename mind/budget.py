"""Budget governor: what has this month cost, and what should Claude do about it?

Every API response carries a `usage` block. `record()` prices it from the table in
config (BudgetConfig.prices) and writes one row to a SQLite ledger. Nothing here
estimates — it only adds up what the API reported.

What gets counted, per response:
  - input_tokens               uncached input            x input price
  - cache_read_input_tokens    prefix served from cache  x cache_read price
  - cache_creation (5m / 1h)   prefix written to cache   x cache_write_5m / _1h price
  - output_tokens              reply + thinking          x output price
  - server_tool_use.web_search_requests                  x $10 per 1,000
  - usage.iterations: when present it is the true per-step breakdown, and two
    things in it are NOT in the top-level totals:
      * a `compaction` step (the server summarising old turns), and
      * a `fallback_message` step, which is billed at the FALLBACK model's price.
    So when iterations are present we price each one at its own model and ignore
    the top-level token fields.
  - batch jobs are half price (BudgetConfig.batch_discount).

Levels (fraction of the monthly cap):
  ok     below 70 %
  warn   70 % or more  -> warn Nick once per month: log, state/alerts.log, and the
                          optional `alert_command` (run with the message as its
                          last argument; unset by default, nothing is wired up)
  brief  90 % or more  -> the engine tells Claude to keep answers short
  over   100 % or more -> with stop_at_cap the engine answers locally, no API call

The governor never changes the model. It has no way to: the model name lives in
ClaudeConfig and nothing here writes to it.

Months are calendar months in UTC, to line up with the Anthropic Console's
monthly spend limit.
"""

from __future__ import annotations

import logging
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import BudgetConfig, Price

log = logging.getLogger(__name__)

MILLION = 1_000_000


@dataclass
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0


@dataclass
class Status:
    month: str
    spent_usd: float
    cap_usd: float
    level: str          # ok / warn / brief / over

    @property
    def fraction(self) -> float:
        return self.spent_usd / self.cap_usd if self.cap_usd > 0 else 1.0


def _get(obj, name, default=0):
    """Read a field from an SDK object or a plain dict; missing/None -> default."""
    if obj is None:
        return default
    value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
    return default if value is None else value


def counts_from(usage_like) -> TokenCounts:
    """Token counts from a usage block or one usage.iterations entry."""
    written = _get(usage_like, "cache_creation_input_tokens")
    split = _get(usage_like, "cache_creation", None)
    if split is not None:
        w5 = _get(split, "ephemeral_5m_input_tokens")
        w1 = _get(split, "ephemeral_1h_input_tokens")
    else:
        # No TTL breakdown: assume the dearer 1-hour price (we only ask for 1h).
        w5, w1 = 0, written
    return TokenCounts(
        input=_get(usage_like, "input_tokens"),
        output=_get(usage_like, "output_tokens"),
        cache_read=_get(usage_like, "cache_read_input_tokens"),
        cache_write_5m=w5,
        cache_write_1h=w1,
    )


class BudgetGovernor:
    def __init__(self, cfg: BudgetConfig, db_path: Path | str, alerts_path: Path | str | None = None,
                 now=lambda: datetime.now(timezone.utc)):
        if cfg.monthly_cap_usd is None or cfg.monthly_cap_usd <= 0:
            raise ValueError("budget.monthly_cap_usd must be set (in US$) in the mind config: "
                             "it is the robot's monthly running allowance and has no default")
        self.cfg = cfg
        self.now = now
        self.alerts_path = Path(alerts_path) if alerts_path else None
        self.alert_process: subprocess.Popen | None = None
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                month TEXT NOT NULL,
                kind TEXT NOT NULL,          -- chat / batch
                model TEXT NOT NULL,
                input_tokens INTEGER, output_tokens INTEGER,
                cache_read_tokens INTEGER, cache_write_5m_tokens INTEGER, cache_write_1h_tokens INTEGER,
                web_searches INTEGER,
                cost_usd REAL NOT NULL
            )""")
        self.db.execute("CREATE TABLE IF NOT EXISTS budget_warnings (month TEXT PRIMARY KEY, ts TEXT)")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(ledger)")}
        if "notional_usd" not in columns:
            # What plan usage (the claude_code brain) would have cost on the API. Logged, not counted.
            self.db.execute("ALTER TABLE ledger ADD COLUMN notional_usd REAL")
        self.db.commit()

    # ------------------------------------------------------------------ pricing
    def price_for(self, model: str) -> Price:
        if model in self.cfg.prices:
            return self.cfg.prices[model]
        # Unknown model: price it at the dearest row we know, loudly, so spend is
        # over-counted rather than under-counted. Fix the table in config.
        dearest = max(self.cfg.prices.values(), key=lambda p: p.output)
        log.error("no price for model %r — charging it at the dearest known rates; "
                  "add it to [budget.prices] in the config", model)
        return dearest

    def cost_of(self, counts: TokenCounts, model: str, *, batch: bool = False) -> float:
        p = self.price_for(model)
        usd = (counts.input * p.input
               + counts.output * p.output
               + counts.cache_read * p.cache_read
               + counts.cache_write_5m * p.cache_write_5m
               + counts.cache_write_1h * p.cache_write_1h) / MILLION
        if batch:
            usd *= self.cfg.batch_discount
        return usd

    def price_usage(self, usage, model: str, *, batch: bool = False) -> tuple[float, list[tuple[str, TokenCounts]]]:
        """Price one response's usage. Returns (US$, [(model, counts), ...])."""
        parts: list[tuple[str, TokenCounts]] = []
        iterations = _get(usage, "iterations", None)
        if iterations:
            for it in iterations:
                kind = _get(it, "type", "message")
                it_model = _get(it, "model", None) or model
                if kind == "compaction":
                    it_model = model   # the summary is written by the model we asked for
                parts.append((it_model, counts_from(it)))
        else:
            parts.append((model, counts_from(usage)))

        usd = sum(self.cost_of(c, m, batch=batch) for m, c in parts)
        searches = _get(_get(usage, "server_tool_use", None), "web_search_requests")
        usd += searches * self.cfg.web_search_per_1000_usd / 1000
        return usd, parts

    # ------------------------------------------------------------------ ledger
    def month_key(self) -> str:
        return self.now().astimezone(timezone.utc).strftime("%Y-%m")

    def record(self, usage, model: str, *, kind: str = "chat") -> float:
        """Price a response's usage and add it to this month's ledger. Returns US$."""
        usd, parts = self.price_usage(usage, model, batch=(kind == "batch"))
        searches = _get(_get(usage, "server_tool_use", None), "web_search_requests")
        served_by = {m for m, _ in parts}
        if served_by - {model}:
            log.info("part of this response was served by %s (refusal fallback)", sorted(served_by - {model}))
        total = TokenCounts()
        for _, c in parts:
            total.input += c.input
            total.output += c.output
            total.cache_read += c.cache_read
            total.cache_write_5m += c.cache_write_5m
            total.cache_write_1h += c.cache_write_1h
        ts = self.now().astimezone(timezone.utc)
        self.db.execute(
            "INSERT INTO ledger (ts, month, kind, model, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_5m_tokens, cache_write_1h_tokens, web_searches, cost_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts.isoformat(), ts.strftime("%Y-%m"), kind, ",".join(sorted(served_by)),
             total.input, total.output, total.cache_read, total.cache_write_5m, total.cache_write_1h,
             searches, usd))
        self.db.commit()
        self._maybe_warn()
        return usd

    def record_plan(self, usage: dict, model: str, notional_usd: float) -> None:
        """Log one claude_code-brain turn. It runs on a Claude plan, so it costs
        US$0 against the API cap; the CLI's own estimate of the API price is kept
        in `notional_usd` so the two brains can be compared."""
        c = counts_from(usage)
        ts = self.now().astimezone(timezone.utc)
        searches = _get(_get(usage, "server_tool_use", None), "web_search_requests")
        self.db.execute(
            "INSERT INTO ledger (ts, month, kind, model, input_tokens, output_tokens, cache_read_tokens, "
            "cache_write_5m_tokens, cache_write_1h_tokens, web_searches, cost_usd, notional_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts.isoformat(), ts.strftime("%Y-%m"), "plan", model, c.input, c.output, c.cache_read,
             c.cache_write_5m, c.cache_write_1h, searches, 0.0, notional_usd))
        self.db.commit()

    def spent_this_month(self) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ledger WHERE month = ?",
                              (self.month_key(),)).fetchone()
        return float(row[0])

    def status(self) -> Status:
        spent = self.spent_this_month()
        cap = self.cfg.monthly_cap_usd
        fraction = spent / cap if cap > 0 else 1.0
        if fraction >= 1.0:
            level = "over"
        elif fraction >= self.cfg.brief_fraction:
            level = "brief"
        elif fraction >= self.cfg.warn_fraction:
            level = "warn"
        else:
            level = "ok"
        return Status(month=self.month_key(), spent_usd=spent, cap_usd=cap, level=level)

    def _maybe_warn(self) -> None:
        st = self.status()
        if st.level == "ok":
            return
        month = st.month
        if self.db.execute("SELECT 1 FROM budget_warnings WHERE month = ?", (month,)).fetchone():
            return
        self.db.execute("INSERT INTO budget_warnings (month, ts) VALUES (?, ?)",
                        (month, self.now().isoformat()))
        self.db.commit()
        text = (f"Claude-body API spend for {month} has reached US${st.spent_usd:.2f} "
                f"of the US${st.cap_usd:.2f} cap ({st.fraction:.0%}).")
        log.warning(text)
        if self.alerts_path:
            self.alerts_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.alerts_path, "a", encoding="utf-8") as f:
                f.write(f"{self.now().isoformat()}  {text}\n")
        if self.cfg.alert_command:
            try:
                # Fire and forget, so a slow command can't hold up a conversation.
                self.alert_process = subprocess.Popen(shlex.split(self.cfg.alert_command) + [text],
                                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                log.error("alert_command failed to start: %s", e)
