"""Budget governor: pricing maths, the monthly ledger, and the 70 % / 90 % / 100 % behaviour."""

from datetime import datetime, timezone

import pytest

from mind.budget import BudgetGovernor
from mind.config import BudgetConfig
from mind.engine import CANNED
from mind.fake_llm import FakeClaude, text_reply
from tests.conftest import heard, make_engine


def governor(tmp_path, cap=100.0, now=None):
    cfg = BudgetConfig(monthly_cap_usd=cap)
    return BudgetGovernor(cfg, tmp_path / "b.db", alerts_path=tmp_path / "alerts.log",
                          now=now or (lambda: datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc)))


def test_cap_is_required(tmp_path):
    with pytest.raises(ValueError, match="monthly_cap_usd"):
        BudgetGovernor(BudgetConfig(), tmp_path / "b.db")


def test_prices_one_exchange_exactly(tmp_path):
    g = governor(tmp_path)
    # The DESIGN.md example: 25k cached prefix, 2k new input, 600 output.
    u = {"input_tokens": 2000, "output_tokens": 600, "cache_read_input_tokens": 25000,
         "cache_creation_input_tokens": 0}
    cost = g.record(u, "claude-opus-5-5")
    # 2000*4 + 600*20 + 25000*0.20 = 8000 + 12000 + 5000 = 25000 per million -> $0.025
    assert cost == pytest.approx(0.025)
    assert g.spent_this_month() == pytest.approx(0.025)


def test_cache_writes_priced_by_ttl(tmp_path):
    g = governor(tmp_path)
    u = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
         "cache_creation_input_tokens": 1_500_000,
         "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000, "ephemeral_5m_input_tokens": 500_000}}
    # 1h writes are 2 x $4 = $8/M; 5m writes are 1.25 x $4 = $5/M
    assert g.record(u, "claude-opus-5-5") == pytest.approx(8.0 + 2.5)
    no_split = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    assert g.record(no_split, "claude-opus-5-5") == pytest.approx(8.0), "unknown TTL priced as 1h (dearer)"


def test_compaction_and_fallback_iterations_counted(tmp_path):
    g = governor(tmp_path)
    u = {
        "input_tokens": 1000, "output_tokens": 100,   # top level excludes compaction
        "iterations": [
            {"type": "compaction", "input_tokens": 150_000, "output_tokens": 3_000,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "message", "input_tokens": 500, "output_tokens": 50,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 500, "output_tokens": 50,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        ],
        "server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 0},
    }
    expected = ((150_000 * 4 + 3_000 * 20) / 1e6          # compaction at Opus 5.5
                + (500 * 4 + 50 * 20) / 1e6                # declined hop at Opus 5.5
                + (500 * 5 + 50 * 25) / 1e6                # fallback served by Opus 4.8 at its rates
                + 3 * 10 / 1000)                           # 3 web searches at $10/1000
    assert g.record(u, "claude-opus-5-5") == pytest.approx(expected)


def test_works_with_real_sdk_usage_objects(tmp_path):
    g = governor(tmp_path)
    reply = FakeClaude()._message(text_reply("hi", input_tokens=1000, output_tokens=100, cache_read=10_000,
                                             cache_write_1h=2_000, web_searches=1))
    expected = (1000 * 4 + 100 * 20 + 10_000 * 0.2 + 2_000 * 8) / 1e6 + 0.01
    assert g.record(reply.usage, "claude-opus-5-5") == pytest.approx(expected)


def test_batch_is_half_price(tmp_path):
    g = governor(tmp_path)
    u = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    assert g.record(u, "claude-opus-5-5", kind="batch") == pytest.approx((4.0 + 2.0) / 2)


def test_unknown_model_charged_at_dearest_known_rate(tmp_path):
    g = governor(tmp_path)
    assert g.record({"input_tokens": 0, "output_tokens": 1_000_000}, "claude-mystery-9") == pytest.approx(25.0)


def test_thresholds_and_one_warning_per_month(tmp_path):
    g = governor(tmp_path, cap=10.0)
    per_dollar = {"input_tokens": 250_000, "output_tokens": 0}       # exactly $1.00
    for _ in range(6):
        g.record(per_dollar, "claude-opus-5-5")
    assert g.status().level == "ok" and g.status().spent_usd == pytest.approx(6.0)
    g.record(per_dollar, "claude-opus-5-5")
    assert g.status().level == "warn"                                  # 70 %
    alerts = (tmp_path / "alerts.log").read_text()
    assert "70%" in alerts and alerts.count("\n") == 1
    g.record(per_dollar, "claude-opus-5-5")
    g.record(per_dollar, "claude-opus-5-5")
    assert g.status().level == "brief"                                 # 90 %
    g.record(per_dollar, "claude-opus-5-5")
    assert g.status().level == "over"                                  # 100 %
    assert (tmp_path / "alerts.log").read_text().count("\n") == 1, "warned once this month"


def test_new_month_starts_from_zero(tmp_path):
    when = {"t": datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)}
    g = governor(tmp_path, cap=10.0, now=lambda: when["t"])
    g.record({"input_tokens": 3_000_000, "output_tokens": 0}, "claude-opus-5-5")     # $12 of $10
    assert g.status().level == "over"
    when["t"] = datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc)
    assert g.status().level == "ok" and g.spent_this_month() == 0


# ----------------------------------------------------- what the engine does
async def test_engine_sends_be_brief_note_once_at_90_percent(mind_cfg, clock, tmp_path):
    mind_cfg.budget.monthly_cap_usd = 1.0
    fake = FakeClaude(script=[text_reply("one"), text_reply("two")])
    engine, body, budget = make_engine(mind_cfg, clock, fake)
    budget.record({"input_tokens": 230_000, "output_tokens": 0}, "claude-opus-5-5")     # $0.92
    await engine.run_turn([heard("tell me a story")])
    await engine.run_turn([heard("another one")])
    notes = [m["content"] for m in fake.requests[1]["messages"] if m["role"] == "system" and m.get("content")]
    assert sum("Budget: brief" in n for n in notes) == 1
    assert fake.requests[0]["model"] == fake.requests[1]["model"] == "claude-opus-5-5", "never changes model"
    assert fake.problems == []


async def test_engine_over_cap_answers_locally_without_api_call(mind_cfg, clock, tmp_path):
    mind_cfg.budget.monthly_cap_usd = 1.0
    fake = FakeClaude()
    engine, body, budget = make_engine(mind_cfg, clock, fake)
    budget.record({"input_tokens": 300_000, "output_tokens": 0}, "claude-opus-5-5")     # $1.20
    await engine.run_turn([heard("hello")])
    assert fake.requests == []
    assert body.calls == [("say", {"text": CANNED["over_budget"]})]


async def test_engine_records_every_response(mind_cfg, clock, tmp_path):
    fake = FakeClaude(script=[text_reply("hi", input_tokens=1000, output_tokens=100, cache_read=0, cache_write_1h=0)])
    engine, body, budget = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("hello")])
    assert budget.spent_this_month() == pytest.approx((1000 * 4 + 100 * 20) / 1e6)
