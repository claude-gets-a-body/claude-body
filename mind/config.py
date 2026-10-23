"""Mind settings.

Defaults live here. A TOML file (see config/mind.example.toml) can override any of
them. Secrets never go in the file — they come from environment variables:

    BODY_TOKEN         shared secret the body must send as "Authorization: Bearer ..."
    ANTHROPIC_API_KEY  only needed for --live
    HA_TOKEN           Home Assistant long-lived token (read-only use)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


@dataclass
class Price:
    """US$ per million tokens (and per 1,000 web searches)."""
    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


def default_prices() -> dict[str, Price]:
    # From https://platform.claude.com/docs/en/about-claude/pricing (checked 2026-10-23).
    # Cache writes: 5-minute = 1.25 x input, 1-hour = 2 x input.
    # Opus 4.8 / Opus 5 are here because a server-side refusal fallback can be
    # served by one of them; their tokens are billed at their own rates.
    return {
        "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20,
                                 cache_write_5m=5.00, cache_write_1h=8.00),
        "claude-opus-5": Price(input=5.00, output=25.00, cache_read=0.50,
                               cache_write_5m=6.25, cache_write_1h=10.00),
        "claude-opus-4-8": Price(input=5.00, output=25.00, cache_read=0.50,
                                 cache_write_5m=6.25, cache_write_1h=10.00),
    }


@dataclass
class BudgetConfig:
    # REQUIRED, no default: the robot's monthly running allowance in US$, set by
    # Nick in the config file. (The US$100 API credit is for building the robot,
    # not for running it.) The governor refuses to start without it.
    monthly_cap_usd: float | None = None
    warn_fraction: float = 0.70        # tell Nick
    brief_fraction: float = 0.90       # ask Claude to keep answers short
    stop_at_cap: bool = True           # at 100%: answer with a canned line, no API call
    # Optional shell command run once when the 70 % warning fires, with the
    # message as its last argument, e.g. "/usr/local/bin/notify-nick". Unset = none.
    alert_command: str | None = None
    web_search_per_1000_usd: float = 10.0
    batch_discount: float = 0.5        # Message Batches API is half price
    prices: dict[str, Price] = field(default_factory=default_prices)


@dataclass
class ClaudeConfig:
    model: str = "claude-opus-5-5"
    effort_chat: str = "low"           # ordinary conversation
    effort_task: str = "medium"        # once a turn turns into a multi-step task
    max_tokens: int = 2048             # chat replies are short; thinking counts towards this
    nightly_max_tokens: int = 16000    # the diary job writes a lot more
    request_timeout_s: float = 300.0
    compact_trigger_tokens: int = 150000   # API minimum is 50,000
    web_search_max_uses: int = 5
    use_fallbacks: bool = True         # fallbacks: "default" on refusals


@dataclass
class ClaudeCodeConfig:
    """The `claude_code` brain (mind/cc_brain.py): a locked-down `claude` CLI
    process on a Claude plan, instead of the API."""
    executable: str = "claude"
    model: str = "claude-opus-5-5"
    effort: str = "low"                # fixed for the whole process
    work_dir: str = str(PROJECT_DIR / "state" / "cc-brain")   # its HOME, config dir and cwd
    turn_timeout_s: float = 300.0
    token_env: str = "CLAUDE_CODE_OAUTH_TOKEN"   # env var holding the `claude setup-token` token
    extra_env: dict[str, str] = field(default_factory=dict)  # TESTS ONLY (e.g. a local fake API)


@dataclass
class HouseConfig:
    """Home Assistant, READ ONLY. The client can only GET /api/states."""
    url: str = "http://homeassistant.local:8123"
    timeout_s: float = 5.0
    # fnmatch patterns. An entity must match `allow` and must not match `deny`.
    # An empty allow list means nothing is readable.
    allow: list[str] = field(default_factory=lambda: [
        "binary_sensor.*door*", "binary_sensor.*window*", "binary_sensor.raining",
        "sensor.*temperature*", "sensor.*humidity*", "sensor.outdoor_*",
        "weather.*", "sun.sun", "light.*",
    ])
    deny: list[str] = field(default_factory=lambda: [
        "camera.*", "person.*", "device_tracker.*", "alarm_control_panel.*",
        "lock.*", "*garage*", "zone.*",
    ])
    max_results: int = 25


@dataclass
class ToolTimeouts:
    """Seconds the mind waits for the body to answer a tool_call."""
    default: float = 20.0
    say: float = 90.0
    look: float = 15.0
    go_to: float = 240.0
    approach: float = 120.0
    dock: float = 300.0


@dataclass
class MindConfig:
    brain: str = "api"                 # "api" (Claude API, needs a key) or "claude_code" (a plan login)
    host: str = "0.0.0.0"
    port: int = 8765
    path: str = "/body"
    state_dir: str = str(PROJECT_DIR / "state")              # SQLite db + day histories
    memory_dir: str = str(PROJECT_DIR / "state" / "memories")  # the live /memories
    memory_template_dir: str = str(PROJECT_DIR / "memories")   # copied in on first run
    day_starts_at: str = "04:00"       # Perth; one conversation per day
    nightly_after: str = "04:15"       # Perth; consolidate the day that just ended
    nightly_poll_s: float = 300.0
    touch_turn_min_gap_s: float = 30.0  # a pat starts a Claude turn at most this often
    min_stt_conf: float = 0.55          # quieter/unclear speech is ignored: no API call
    event_repeat_s: float = 1800.0      # the same body event won't start another turn within this
    retention_days: int = 30            # state/days logs and transcripts are deleted after this
    events_that_start_a_turn: list[str] = field(default_factory=lambda: [
        "drop", "low_battery", "stuck", "pack_hot", "tilt",
    ])
    listen_after_question_s: float = 8.0
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    house: HouseConfig = field(default_factory=HouseConfig)
    tool_timeouts: ToolTimeouts = field(default_factory=ToolTimeouts)

    # secrets (from the environment only)
    body_token: str = ""
    ha_token: str = ""

    @property
    def db_path(self) -> Path:
        return Path(self.state_dir) / "mind.db"


def _apply(obj, data: dict) -> None:
    """Copy values from a TOML table onto a dataclass, recursing into sub-tables."""
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"unknown setting {key!r} in [{type(obj).__name__}]")
        current = getattr(obj, key)
        if key == "extra_env" and isinstance(value, dict):
            setattr(obj, key, dict(value))
        elif key == "prices" and isinstance(value, dict):
            # merge: models in the file override the built-in rows, the rest stay
            current.update({model: Price(**p) for model, p in value.items()})
        elif is_dataclass(current) and isinstance(value, dict):
            _apply(current, value)
        else:
            setattr(obj, key, value)


def load(path: str | None = None) -> MindConfig:
    cfg = MindConfig()
    if path:
        with open(path, "rb") as f:
            _apply(cfg, tomllib.load(f))
    cfg.body_token = os.environ.get("BODY_TOKEN", cfg.body_token)
    cfg.ha_token = os.environ.get("HA_TOKEN", cfg.ha_token)
    return cfg
