"""Nightly diary job via the (fake) Message Batches API."""

import json

import pytest

from mind.fake_llm import FakeClaude
from mind.nightly import NightlyJob
from tests.conftest import heard, make_engine, perth


def job(mind_cfg, clock, fake, engine):
    return NightlyJob(mind_cfg, fake, engine.memory, engine.transcripts, engine.budget, clock,
                      "Write the diary (test prompt).")


async def test_diary_written_after_the_day_ends(mind_cfg, clock):
    fake = FakeClaude()
    engine, _, budget = make_engine(mind_cfg, clock, fake)
    clock.set(perth(2026, 10, 23, 16, 0))
    await engine.run_turn([heard("I got a gold star at school today")])
    nightly = job(mind_cfg, clock, fake, engine)

    clock.set(perth(2026, 10, 24, 4, 10))         # day over, but before 04:15
    assert await nightly.submit_ready() == []
    clock.set(perth(2026, 10, 24, 4, 20))
    spent_before = budget.spent_this_month()
    from datetime import date
    assert await nightly.submit_ready() == [date(2026, 10, 23)]
    assert await nightly.submit_ready() == [], "submitted once only"

    request = next(iter(fake.batches.values()))[0]
    assert request["custom_id"] == "diary-2026-10-23"
    params = request["params"]
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in params and "tool_choice" not in params
    assert "gold star" in params["messages"][0]["content"]

    assert await nightly.collect_finished() == [date(2026, 10, 23)]
    diary = engine.memory.read_text("/memories/diary/2026-10-23.md")
    assert diary.startswith("# 2026-10-23")
    assert "(fake) checked on 2026-10-23" in engine.memory.read_text("/memories/promises.md")
    # batch tokens are half price: (3000*4 + 600*20)/1e6 / 2 = 0.012
    assert budget.spent_this_month() - spent_before == pytest.approx(0.012)


async def test_disallowed_paths_from_the_model_are_skipped(mind_cfg, clock, tmp_path):
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    nightly = job(mind_cfg, clock, fake, engine)

    class R:  # minimal stand-in for a batch result
        custom_id = "diary-2026-10-23"

        class result:
            type = "succeeded"

            class message:
                model = "claude-opus-5-5"
                stop_reason = "end_turn"
                usage = {"input_tokens": 1, "output_tokens": 1}
                content = [type("B", (), {"type": "text", "text": json.dumps({
                    "diary": "# day", "file_updates": [
                        {"path": "/memories/../../evil.md", "content": "x"},
                        {"path": "/memories/me.md", "content": "# Me\nupdated"},
                        {"path": "/memories/people/Bad Name.md", "content": "x"},
                    ]})})()]

    from datetime import date
    nightly._apply(date(2026, 10, 23), [R])
    assert engine.memory.read_text("/memories/me.md").startswith("# Me\nupdated")
    assert not (tmp_path / "evil.md").exists()
    assert not (engine.memory.root / "people" / "Bad Name.md").exists()
