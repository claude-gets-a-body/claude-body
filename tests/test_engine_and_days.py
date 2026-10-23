"""Conversation engine: day rollover, frozen prefix, append-only history,
compaction, effort switching, failures, and restarts."""

import json
from pathlib import Path

from mind.engine import CANNED
from mind.fake_llm import FakeClaude, text_reply, tool_reply
from tests.conftest import FakeBody, heard, make_engine, perth


def files(mind_cfg):
    return sorted(p.name for p in (Path(mind_cfg.state_dir) / "days").glob("*"))


async def test_one_conversation_per_day_rolls_over_at_4am(mind_cfg, clock):
    fake = FakeClaude()
    engine, body, _ = make_engine(mind_cfg, clock, fake)

    clock.set(perth(2026, 10, 23, 23, 50))
    await engine.run_turn([heard("still up?")])
    clock.set(perth(2026, 10, 24, 3, 59))       # after midnight, before 04:00: same day
    await engine.run_turn([heard("can't sleep")])
    assert engine.day.day.isoformat() == "2026-10-23"
    assert len(fake.requests[1]["messages"]) > len(fake.requests[0]["messages"])

    # Nick edits INDEX.md during the day: today's prefix must NOT change
    engine.memory.write_text("/memories/INDEX.md", "# Memory index\n- people/sam.md: Sam\n")
    clock.set(perth(2026, 10, 24, 3, 59))
    await engine.run_turn([heard("one more")])
    assert fake.requests[2]["system"] == fake.requests[0]["system"]

    clock.set(perth(2026, 10, 24, 4, 0))        # new conversation day
    await engine.run_turn([heard("good morning")])
    assert engine.day.day.isoformat() == "2026-10-24"
    new = fake.requests[3]
    assert new["messages"][0]["role"] == "user" and "good morning" in new["messages"][0]["content"]
    assert len(new["messages"]) == 2                          # user + context note, nothing from yesterday
    assert "people/sam.md" in new["system"][1]["text"]        # fresh INDEX for the new day
    note = new["messages"][1]["content"]
    assert "first conversation of a new day" in note and "diary/2026-10-23.md" in note
    assert files(mind_cfg) == ["2026-10-23.s1.jsonl", "2026-10-23.s1.prefix.json",
                               "2026-10-24.s1.jsonl", "2026-10-24.s1.prefix.json"]
    assert fake.problems == []


async def test_request_shape_cache_and_context_placement(mind_cfg, clock):
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("hello there")])
    r = fake.requests[0]
    assert r["model"] == "claude-opus-5-5"
    assert r["thinking"] == {"type": "adaptive"}
    assert r["output_config"] == {"effort": "low"}
    assert r["fallbacks"] == "default"
    assert set(r["betas"]) >= {"compact-2026-01-12", "server-side-fallback-2026-07-01"}
    assert "tool_choice" not in r
    assert r["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert r["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert r["context_management"]["edits"][0]["type"] == "compact_20260112"
    names = [t.get("name") for t in r["tools"]]
    assert names[-2:] == ["memory", "web_search"]
    assert r["tools"][-1] == {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
    assert r["tools"][-2] == {"type": "memory_20250818", "name": "memory"}
    # volatile context is a system MESSAGE after the user turn, not in the system prompt
    assert [m["role"] for m in r["messages"]] == ["user", "system"]
    assert "Context update" in r["messages"][1]["content"]
    assert "Context update" not in json.dumps(r["system"])


async def test_history_is_append_only_across_many_turns_with_tools(mind_cfg, clock):
    fake = FakeClaude()
    engine, body, _ = make_engine(mind_cfg, clock, fake)
    for text in ["hi", "look at this", "remember that Sam likes dinosaurs", "is the back door open",
                 "remind me in 5 minutes to feed the cat", "what did Sam say about dinosaurs", "thanks"]:
        await engine.run_turn([heard(text)])
    # FakeClaude checks every request is the previous one plus new messages at the end
    assert fake.problems == []
    assert len(fake.requests) >= 12
    assert engine.memory.read_text("/memories/notes/fake-4.md") or any(
        (Path(mind_cfg.memory_dir) / "notes").glob("*.md"))
    assert engine.timers.pending()[0]["note"].startswith("feed the cat")
    on_disk = [json.loads(l) for l in (Path(mind_cfg.state_dir) / "days" / "2026-10-23.s1.jsonl").read_text().splitlines()]
    assert on_disk == engine.day.messages


async def test_compaction_block_is_kept_in_history(mind_cfg, clock):
    fake = FakeClaude(compact_after_messages=6)
    engine, _, budget = make_engine(mind_cfg, clock, fake)
    for i in range(5):
        await engine.run_turn([heard(f"message {i}")])
    blocks = [b for m in engine.day.messages if m["role"] == "assistant" for b in m["content"]]
    compaction = [b for b in blocks if b["type"] == "compaction"]
    assert compaction == [{"type": "compaction", "content": "Summary so far: (fake) the family chatted with Claude."}]
    later = fake.requests[-1]["messages"]
    assert any(b.get("type") == "compaction" for m in later if m["role"] == "assistant" for b in m["content"])
    assert budget.spent_this_month() > 0.6, "compaction iteration (150k input) was billed"
    assert fake.problems == []


async def test_effort_raised_for_tasks_then_lowered_again(mind_cfg, clock):
    fake = FakeClaude(script=[tool_reply("go_to", {"place": "kitchen"}), text_reply("Here!"),
                              text_reply("Hello again")])
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("go to the kitchen")])
    second = fake.requests[1]["messages"]
    assert second[-2] == {"role": "system", "content": [], "output_config": {"effort": "medium"}}
    assert second[-1]["content"][0]["type"] == "tool_result"
    await engine.run_turn([heard("hi")])
    third = fake.requests[2]["messages"]
    low = [m for m in third if m.get("output_config") == {"effort": "low"}]
    assert len(low) == 1 and fake.requests[2]["output_config"] == {"effort": "low"}, "top level never changes"
    assert fake.problems == []


async def test_api_failure_speaks_and_next_turn_is_still_valid(mind_cfg, clock):
    def boom(params):
        raise ConnectionError("network down")

    fake = FakeClaude(script=[tool_reply("look", {}), boom, text_reply("Back now.")])
    engine, body, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("look at this")])
    assert ("say", {"text": CANNED["api_error"]}) in body.calls
    # the look result never reached Claude; it is kept and sent next turn
    await engine.run_turn([heard("hello?")])
    last = fake.requests[-1]["messages"]
    results = [m for m in last if m["role"] == "user" and isinstance(m["content"], list)]
    assert results and results[-1]["content"][0]["type"] == "tool_result"
    assert not results[-1]["content"][0].get("is_error")
    assert any("hello?" in m["content"] for m in last if isinstance(m["content"], str))
    assert fake.problems == []


async def test_restart_starts_a_new_segment_seeded_from_the_transcript(mind_cfg, clock):
    """After a restart the saved history is NOT replayed (it has photos removed, so
    it differs from what the model saw). A new segment starts with a text seed."""
    fake = FakeClaude()
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("my name is Sam and I like dinosaurs")])
    await engine.run_turn([heard("look at this")])
    first_segment_len = len(fake.requests[-1]["messages"])

    engine2, _, _ = make_engine(mind_cfg, clock, fake)        # a "restarted" mind
    await engine2.run_turn([heard("what's my name?")])
    new = fake.requests[-1]
    assert engine2.day.segment == 2
    assert len(new["messages"]) == 2 < first_segment_len, "fresh conversation, nothing replayed"
    first = new["messages"][0]["content"]
    assert first.startswith("[earlier today")
    assert "my name is Sam and I like dinosaurs" in first and "Let me have a look." in first
    assert first.rstrip().endswith('[heard] Sam: "what\'s my name?" (voice from ahead)')
    assert files(mind_cfg) == ["2026-10-23.s1.jsonl", "2026-10-23.s1.prefix.json",
                               "2026-10-23.s2.jsonl", "2026-10-23.s2.prefix.json"]
    assert fake.problems == []


async def test_refusal_gets_a_gentle_line(mind_cfg, clock):
    fake = FakeClaude(script=[{"content": [], "stop_reason": "refusal",
                               "usage": {"input_tokens": 10, "output_tokens": 0}}])
    engine, body, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("something")])
    assert body.calls[-1] == ("say", {"text": CANNED["refusal"]})


async def test_handled_stop_words_and_question_opens_listening(mind_cfg, clock):
    fake = FakeClaude(script=[text_reply("Okay, I've stopped. Want me to go back to my dock?")])
    engine, body, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("stop!", handled="stop")])
    user = fake.requests[0]["messages"][0]["content"]
    assert "your body already obeyed 'stop'" in user
    assert {"t": "listen", "seconds": 8.0} in body.sent
    assert body.sent[0] == {"t": "speak_state", "on": True}


async def test_body_tool_errors_and_disconnected_body(mind_cfg, clock):
    fake = FakeClaude(script=[tool_reply("go_to", {"place": "kitchen"}), text_reply("ok")])
    body = FakeBody(handlers={"go_to": lambda a: {"ok": False, "error": "quiet hours"}})
    engine, _, _ = make_engine(mind_cfg, clock, fake, body=body)
    await engine.run_turn([heard("go to the kitchen")])
    res = fake.requests[1]["messages"][-1]["content"][0]
    assert res["is_error"] and res["content"] == "quiet hours"

    body.connected = False
    block = await engine.run_tool("look", "t1", {})
    assert block["is_error"] and "isn't connected" in block["content"]


async def test_touch_turns_are_rate_limited(mind_cfg, clock):
    engine, _, _ = make_engine(mind_cfg, clock, FakeClaude())
    engine.on_body_message({"t": "touch", "g": "pat"})
    engine.on_body_message({"t": "touch", "g": "pat"})
    assert engine.queue.qsize() == 1
    clock.advance(seconds=31)
    engine.on_body_message({"t": "touch", "g": "pat"})
    assert engine.queue.qsize() == 2


async def test_single_lookup_stays_at_chat_effort(mind_cfg, clock):
    fake = FakeClaude(script=[tool_reply("house", {"question": "back door"}), text_reply("It's shut."),
                              tool_reply("recall", {"query": "x"}), tool_reply("look", {}), text_reply("done")])
    engine, _, _ = make_engine(mind_cfg, clock, fake)
    await engine.run_turn([heard("is the back door open")])
    assert not any(m.get("output_config") for m in fake.requests[1]["messages"])
    await engine.run_turn([heard("what did we say, and look")])
    # second tool round in one turn -> raised before the second results go back
    assert fake.requests[4]["messages"][-2] == {"role": "system", "content": [], "output_config": {"effort": "medium"}}
    assert fake.problems == []
