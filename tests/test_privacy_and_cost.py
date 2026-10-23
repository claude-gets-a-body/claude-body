"""Privacy (photos never reach disk, retention) and cost guards (STT confidence,
repeated events, max_tokens, alert_command, cache-write pricing)."""

import base64
import sys
from datetime import date
from pathlib import Path

import pytest

from body.drivers.voice import Utterance
from mind.config import HouseConfig, MindConfig, default_prices
from mind.day import PHOTO_PLACEHOLDER, without_photos
from mind.engine import CANNED
from mind.fake_llm import FakeClaude, text_reply, tool_reply
from mind.nightly import NightlyJob
from tests.conftest import PROJECT, heard, make_engine, perth, wait_for
from tests.test_roundtrip import running

JPEG = (PROJECT / "sim_frames" / "bug.jpg").read_bytes()
JPEG_B64 = base64.b64encode(JPEG).decode()


def every_file_under(*folders):
    for folder in folders:
        for f in Path(folder).rglob("*"):
            if f.is_file():
                yield f


def assert_no_image_data(*folders):
    checked = 0
    for f in every_file_under(*folders):
        data = f.read_bytes()
        checked += 1
        assert b"\xff\xd8\xff" not in data, f"raw JPEG bytes in {f}"
        assert b"/9j/" not in data, f"base64 JPEG in {f}"            # every base64 JPEG starts /9j/
        assert JPEG_B64[1000:1060].encode() not in data, f"photo data in {f}"
        assert b'"type": "image"' not in data and b'"type":"image"' not in data, f"image block in {f}"
    assert checked > 3, "the scan actually looked at files"


# --------------------------------------------------------------- privacy
async def test_no_persisted_file_ever_contains_image_data_end_to_end(mind_cfg, clock):
    """Real WebSocket, real sim body, real SQLite: take photos, then scan every file."""
    fake = FakeClaude(script=[tool_reply("look", {"at": "ahead"}, "Let me look."), text_reply("A beetle!"),
                              tool_reply("look", {"at": "left"}), text_reply("A kitchen.")])
    async with running(mind_cfg, clock, fake) as (mind, body):
        body.agent.voice.hear(Utterance(text="what's this bug, can you look"))
        await wait_for(lambda: len(fake.requests) == 2)
        body.agent.voice.hear(Utterance(text="and look over there"))
        await wait_for(lambda: len(fake.requests) == 4 and "A kitchen." in body.agent.voice.spoken)

        # the model saw the photos, and still sees them later in the same conversation (RAM)
        later = fake.requests[3]["messages"]
        images = [c for m in later if isinstance(m["content"], list) for b in m["content"]
                  if b.get("type") == "tool_result" and isinstance(b.get("content"), list)
                  for c in b["content"] if c.get("type") == "image"]
        assert len(images) == 2
        # ...but on disk they're placeholders
        log = next((Path(mind_cfg.state_dir) / "days").glob("*.jsonl")).read_text()
        assert log.count(PHOTO_PLACEHOLDER) == 2
    assert_no_image_data(mind_cfg.state_dir, mind_cfg.memory_dir)


def test_without_photos_replaces_every_image_block():
    msg = {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": [
            {"type": "text", "text": "Photo taken."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": JPEG_B64}}]},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": JPEG_B64}}]}
    clean = without_photos(msg)
    assert JPEG_B64 not in str(clean) and str(clean).count(PHOTO_PLACEHOLDER) == 2
    assert msg["content"][1]["type"] == "image", "the original (RAM) copy is untouched"


async def test_retention_prunes_old_logs_and_transcripts(mind_cfg, clock):
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    for d in (date(2026, 9, 1), date(2026, 9, 22), date(2026, 9, 23), date(2026, 10, 23)):
        clock.set(perth(d.year, d.month, d.day, 12, 0))
        engine.day = None
        await engine.run_turn([heard(f"hello on {d}")])
    days_dir = Path(mind_cfg.state_dir) / "days"
    assert len(list(days_dir.glob("*.jsonl"))) == 4

    clock.set(perth(2026, 10, 24, 5, 0))
    nightly = NightlyJob(mind_cfg, fake, engine.memory, engine.transcripts, engine.budget, clock, "x")
    counts = nightly.prune(date(2026, 10, 23))          # keep 30 days: cutoff 2026-09-23
    remaining = sorted(f.name.split(".")[0] for f in days_dir.glob("*.jsonl"))
    assert remaining == ["2026-09-23", "2026-10-23"]
    assert counts["files"] == 4 and counts["transcript_rows"] >= 4
    assert engine.transcripts.search("hello") and all(
        h["day"] >= "2026-09-23" for h in engine.transcripts.search("hello", limit=50))
    assert "2026-09-01" not in engine.transcripts.recall("hello"), "pruned rows are gone from search too"


def test_retention_is_configurable():
    assert MindConfig().retention_days == 30


# ------------------------------------------------------------------ cost
async def test_low_confidence_speech_makes_no_api_call(mind_cfg, clock):
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    engine.on_body_message({"t": "heard", "text": "mumble", "speaker": None, "doa": 0, "conf": 0.4, "id": "u1"})
    assert engine.queue.empty()
    engine.on_body_message({"t": "heard", "text": "stop", "speaker": None, "doa": 0, "conf": 0.3, "id": "u2",
                            "handled": "stop"})
    assert engine.queue.empty() and "obeyed 'stop'" in engine.world.recent_events[-1]
    engine.on_body_message({"t": "heard", "text": "hello", "speaker": None, "doa": 0, "conf": 0.55, "id": "u3"})
    assert engine.queue.qsize() == 1


async def test_repeated_identical_events_start_one_turn(mind_cfg, clock):
    engine, _, _ = make_engine(mind_cfg, clock, FakeClaude())
    drop = {"t": "event", "e": "drop", "detail": "drop_l"}
    for _ in range(4):
        engine.on_body_message(drop)
    assert engine.queue.qsize() == 1
    engine.on_body_message({"t": "event", "e": "drop", "detail": "drop_rear"})   # different: new turn
    assert engine.queue.qsize() == 2
    clock.advance(minutes=31)
    engine.on_body_message(drop)
    assert engine.queue.qsize() == 3
    engine.on_body_message({"t": "event", "e": "bump", "detail": "bump_l"})       # never starts a turn
    assert engine.queue.qsize() == 3 and "bump" in engine.world.recent_events


async def test_chat_max_tokens_is_small_and_nightly_is_large(mind_cfg, clock):
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("hi")])
    assert fake.requests[0]["max_tokens"] == 2048
    clock.set(perth(2026, 10, 24, 5, 0))
    nightly = NightlyJob(mind_cfg, fake, engine.memory, engine.transcripts, engine.budget, clock, "x")
    assert nightly.build_request(date(2026, 10, 23))["params"]["max_tokens"] == 16000


async def test_cut_off_reply_is_handled(mind_cfg, clock):
    fake = FakeClaude(script=[{"content": [{"type": "thinking", "thinking": "", "signature": "s"}],
                               "stop_reason": "max_tokens", "usage": {"input_tokens": 10, "output_tokens": 2048}}])
    engine, body, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("explain the universe")])
    assert body.calls[-1] == ("say", {"text": CANNED["cut_off"]})


async def test_alert_command_runs_once_with_the_message(mind_cfg, clock, tmp_path):
    out = tmp_path / "alert.txt"
    script = tmp_path / "alert.py"
    script.write_text("import sys, pathlib\npathlib.Path(sys.argv[1]).write_text(sys.argv[2])\n")
    mind_cfg.budget.monthly_cap_usd = 1.0
    mind_cfg.budget.alert_command = f"{sys.executable} {script} {out}"
    engine, _, budget = make_engine(mind_cfg, clock, FakeClaude())
    budget.record({"input_tokens": 200_000, "output_tokens": 0}, "claude-opus-5-5")      # $0.80 = 80 %
    budget.alert_process.wait(timeout=10)
    assert "80%" in out.read_text() and "US$1.00" in out.read_text()
    first = budget.alert_process
    budget.record({"input_tokens": 10_000, "output_tokens": 0}, "claude-opus-5-5")
    assert budget.alert_process is first, "once per month"


def test_alert_command_unset_by_default():
    from mind.config import BudgetConfig
    assert BudgetConfig().alert_command is None


def test_cache_write_prices_are_the_documented_multiples():
    # skill shared/prompt-caching.md: "Cache writes cost 1.25x for 5-minute TTL, 2x for 1-hour TTL"
    for model, p in default_prices().items():
        assert p.cache_write_1h == pytest.approx(2 * p.input), model
        assert p.cache_write_5m == pytest.approx(1.25 * p.input), model
    assert default_prices()["claude-opus-5-5"].cache_read == pytest.approx(0.05 * 4.0)


def test_home_assistant_defaults_leave_out_covers_and_media():
    allow = HouseConfig().allow
    assert not any(p.startswith(("cover.", "media_player.")) for p in allow)


def test_the_disk_scan_catches_a_leaked_photo(tmp_path):
    """Guard against a vacuous scan: plant a leaked photo and expect failure."""
    for i in range(4):
        (tmp_path / f"ok{i}.txt").write_text("nothing to see")
    (tmp_path / "leak.jsonl").write_text('{"type": "image", "source": {"data": "%s"}}' % JPEG_B64)
    with pytest.raises(AssertionError, match="leak.jsonl"):
        assert_no_image_data(tmp_path)
