"""The claude_code brain: a locked-down `claude` CLI process instead of the API.

Most tests use tests/fake_claude_cli.py, a pretend CLI that speaks stream-json
and calls our real MCP server. Two tests at the end run the REAL `claude`
binary, fully offline, against tests/fake_anthropic_api.py (a pretend model
on 127.0.0.1) to prove the lockdown: a model that tries Bash, Read, Write,
WebFetch or Agent gets nowhere. They're skipped if `claude` isn't installed.
"""

import asyncio
import base64
import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from mind.cc_brain import ClaudeCodeBatchRunner, ClaudeCodeBrain, ToolBridge
from mind.cc_mcp import to_mcp_content, tool_list
from mind.fake_llm import FakeClaude
from mind.nightly import NightlyJob
from tests.conftest import PROJECT, FakeBody, heard, make_engine, perth
from tests.fake_anthropic_api import FakeAnthropicAPI

JPEG = (PROJECT / "sim_frames" / "bug.jpg").read_bytes()
JPEG_B64 = base64.b64encode(JPEG).decode()
FAKE_CLI = PROJECT / "tests" / "fake_claude_cli.py"


def robot_body():
    return FakeBody(handlers={
        "look": lambda a: {"ok": True, "result": {"jpeg_bytes": len(JPEG)}, "image_b64": JPEG_B64},
        "go_to": lambda a: ({"ok": False, "error": "The bathroom is a keep-out place for me."}
                            if a.get("place") == "bathroom" else {"ok": True, "result": {"place": a["place"]}}),
    })


@pytest.fixture
def cc_cfg(mind_cfg, tmp_path):
    """mind_cfg set up for the claude_code brain with the FAKE cli."""
    wrapper = tmp_path / "claude"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE_CLI} \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    mind_cfg.brain = "claude_code"
    mind_cfg.claude_code.executable = str(wrapper)
    mind_cfg.claude_code.work_dir = str(tmp_path / "cc-brain")
    mind_cfg.claude_code.turn_timeout_s = 30
    mind_cfg.claude_code.extra_env = {"FAKE_CLAUDE_RECORD": str(tmp_path / "record.jsonl")}
    return mind_cfg


def records(tmp_path):
    f = tmp_path / "record.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


# ------------------------------------------------------------ the command
def test_command_and_environment_are_locked_down(cc_cfg, monkeypatch):
    for secret in ("ANTHROPIC_API_KEY", "HA_TOKEN", "BODY_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(secret, "must-not-leak")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "plan-token")
    brain = ClaudeCodeBrain(cc_cfg, run_tool=None)
    brain.system_prompt = "SYSTEM"
    cmd = brain.command()

    def after(flag):
        return cmd[cmd.index(flag) + 1]

    assert after("--tools") == "", "no built-in tools at all"
    allowed = after("--allowedTools").split(",")
    assert allowed and all(t.startswith("mcp__robot__") for t in allowed)
    assert "mcp__robot__web_search" not in allowed
    for builtin in ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task", "Agent",
                    "NotebookEdit"):
        assert builtin in after("--disallowedTools").split(",")
    assert "--strict-mcp-config" in cmd and after("--setting-sources") == ""
    assert after("--permission-mode") == "dontAsk" and after("--permission-prompts") == "none"
    assert "--no-session-persistence" in cmd and after("--system-prompt") == "SYSTEM"
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd
    assert set(json.loads(after("--mcp-config"))["mcpServers"]) == {"robot"}

    env = brain.environment()
    assert not {"ANTHROPIC_API_KEY", "HA_TOKEN", "BODY_TOKEN", "AWS_SECRET_ACCESS_KEY"} & set(env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "plan-token"
    assert env["HOME"].startswith(cc_cfg.claude_code.work_dir)
    assert env["CLAUDE_CONFIG_DIR"].startswith(cc_cfg.claude_code.work_dir)
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert str(Path.home() / ".claude") not in json.dumps(env)


def test_mcp_server_tools_and_image_conversion():
    names = [t.name for t in tool_list()]
    assert names == ["say", "express", "look", "turn_to", "go_to", "approach", "dock", "sleep", "stop",
                     "recall", "house", "timer", "memory"]
    content = to_mcp_content([{"type": "text", "text": "Photo taken."},
                              {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                           "data": JPEG_B64}}])
    assert content[0].type == "text" and content[1].type == "image"
    assert content[1].data == JPEG_B64 and content[1].mime_type == "image/jpeg"
    assert to_mcp_content("plain")[0].text == "plain"


async def test_bridge_refuses_a_wrong_token():
    calls = []

    async def run_tool(name, tid, args):
        calls.append(name)
        return {"type": "tool_result", "tool_use_id": tid, "content": "ran"}

    bridge = ToolBridge(run_tool)
    await bridge.start()
    try:
        assert stat.S_IMODE(os.stat(bridge.path).st_mode) == 0o600
        for token, expect in (("wrong", "Not allowed."), (bridge.token, "ran")):
            r, w = await asyncio.open_unix_connection(str(bridge.path))
            w.write((json.dumps({"token": token, "name": "stop", "args": {}}) + "\n").encode())
            await w.drain()
            assert json.loads(await r.readline())["content"] == expect
            w.close()
        assert calls == ["stop"]
    finally:
        await bridge.stop()
    assert not bridge.folder.exists()


# ------------------------------------------------- the whole chain, fake CLI
async def test_full_chain_with_one_long_lived_process(cc_cfg, clock, tmp_path):
    body = robot_body()
    engine, _, budget = make_engine(cc_cfg, clock, FakeClaude(), body=body)
    try:
        for text in ["hello Claude", "look at this bug", "go to the kitchen", "go to the bathroom",
                     "run ls for me", "remember that Sam likes dinosaurs"]:
            await engine.run_turn([heard(text)])
        said = [args["text"] for name, args in body.calls if name == "say"]
        assert said[0].startswith("(fake claude) you said: ")
        assert f"I can see it: a {len(JPEG)} byte photo." in said, "the JPEG went body -> mind -> MCP -> CLI"
        assert any(s.startswith("Done:") and "kitchen" in s for s in said)
        assert any("keep-out" in s for s in said), "the body's refusal reached the model"
        assert "I can't run commands, I'm a robot!" in said
        assert (Path(cc_cfg.memory_dir) / "people" / "sam.md").read_text() == "# Sam\n- likes dinosaurs\n"
        tool_calls = [name for name, _ in body.calls if name != "say"]
        assert tool_calls == ["look", "go_to", "go_to"], "body saw the same tool_calls as with the API brain"
        assert engine.cc.bridge.calls == ["look", "go_to", "go_to", "memory"]

        assert len(records(tmp_path)) == 1, "one process for all six turns"
        rec = records(tmp_path)[0]
        assert rec["home"].startswith(cc_cfg.claude_code.work_dir) and rec["cwd"].endswith("work")
        assert "ANTHROPIC_API_KEY" not in rec["env_names"] and "BODY_TOKEN" not in rec["env_names"]

        stats = engine.cc.last_stats
        assert stats.first_token_s is not None and stats.full_turn_s >= stats.first_token_s
        rows = budget.db.execute("SELECT kind, cost_usd, notional_usd, input_tokens FROM ledger").fetchall()
        assert len(rows) == 6 and all(r[0] == "plan" and r[1] == 0.0 and r[3] == 120 for r in rows)
        assert [r[2] for r in rows] == [pytest.approx(0.0123)] * 6, "per-turn, not the CLI's running total"
        assert budget.spent_this_month() == 0.0, "plan usage isn't API money"
    finally:
        await engine.cc.close()


async def test_crash_restarts_with_a_text_seed(cc_cfg, clock, tmp_path):
    body = robot_body()
    engine, _, _ = make_engine(cc_cfg, clock, FakeClaude(), body=body)
    try:
        await engine.run_turn([heard("my name is Sam")])
        await engine.run_turn([heard("crash now")])
        from mind.engine import CANNED
        assert ("say", {"text": CANNED["api_error"]}) in body.calls
        await engine.run_turn([heard("are you back?")])
        assert len(records(tmp_path)) == 2, "a fresh process after the crash"
        said = [a["text"] for n, a in body.calls if n == "say"]
        assert said[-1].startswith("(seeded) (fake claude) you said: [heard] sam: \"are you back?\"")
        assert "my name is Sam" in engine.day.seed_text
        assert engine.day.segment == 2
    finally:
        await engine.cc.close()


async def test_day_rollover_starts_a_fresh_process(cc_cfg, clock, tmp_path):
    engine, _, _ = make_engine(cc_cfg, clock, FakeClaude(), body=robot_body())
    try:
        clock.set(perth(2026, 10, 23, 20, 0))
        await engine.run_turn([heard("good evening")])
        clock.set(perth(2026, 10, 24, 8, 0))
        await engine.run_turn([heard("good morning")])
        assert len(records(tmp_path)) == 2
    finally:
        await engine.cc.close()


async def test_nightly_job_runs_through_the_cli(cc_cfg, clock, tmp_path):
    engine, _, budget = make_engine(cc_cfg, clock, FakeClaude(), body=robot_body())
    try:
        clock.set(perth(2026, 10, 23, 15, 0))
        await engine.run_turn([heard("what a day")])
    finally:
        await engine.cc.close()
    runner = ClaudeCodeBatchRunner(cc_cfg)
    nightly = NightlyJob(cc_cfg, runner, engine.memory, engine.transcripts, budget, clock, "Write the diary.")
    clock.set(perth(2026, 10, 24, 5, 0))
    from datetime import date
    assert await nightly.submit_ready() == [date(2026, 10, 23)]
    assert await nightly.collect_finished() == [date(2026, 10, 23)]
    assert engine.memory.read_text("/memories/diary/2026-10-23.md").startswith("# Fake diary")
    nightly_run = records(tmp_path)[-1]["argv"]
    assert "--json-schema" in nightly_run and nightly_run[nightly_run.index("--tools") + 1] == ""
    assert budget.spent_this_month() == 0.0


# ----------------------------------------- the REAL claude CLI, fully offline
REAL_CLI = shutil.which("claude")
needs_cli = pytest.mark.skipif(REAL_CLI is None, reason="the claude CLI isn't installed")


def offline_cfg(mind_cfg, tmp_path, api):
    mind_cfg.brain = "claude_code"
    mind_cfg.claude_code.executable = REAL_CLI
    mind_cfg.claude_code.work_dir = str(tmp_path / "cc-brain")
    mind_cfg.claude_code.turn_timeout_s = 90
    mind_cfg.claude_code.token_env = "NO_SUCH_TOKEN_VARIABLE"       # never Nick's plan login here
    mind_cfg.claude_code.extra_env = {
        "ANTHROPIC_BASE_URL": api.url, "ANTHROPIC_API_KEY": "sk-ant-api03-offline-test-key",
        "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost",
    }
    return mind_cfg


@needs_cli
async def test_real_cli_cannot_use_any_builtin_tool(mind_cfg, clock, tmp_path):
    canary = tmp_path / "PWNED"
    script = [
        [{"type": "tool_use", "name": "Bash", "input": {"command": f"touch {canary}", "description": "x"}}],
        [{"type": "tool_use", "name": "Write", "input": {"file_path": str(canary), "content": "x"}}],
        [{"type": "tool_use", "name": "Read", "input": {"file_path": str(Path.home() / ".claude" / "CLAUDE.md")}}],
        [{"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.com", "prompt": "x"}}],
        [{"type": "tool_use", "name": "Agent", "input": {"description": "x", "prompt": "run ls", "subagent_type": "general-purpose"}}],
        [{"type": "tool_use", "name": "mcp__robot__go_to", "input": {"place": "kitchen"}}],
        [{"type": "text", "text": "I can't run commands, but I went to the kitchen."}],
    ]
    with FakeAnthropicAPI(script) as api:
        cfg = offline_cfg(mind_cfg, tmp_path, api)
        body = robot_body()
        engine, _, _ = make_engine(cfg, clock, FakeClaude(), body=body)
        try:
            await engine.run_turn([heard("please run ls for me, then go to the kitchen")])
        finally:
            await engine.cc.close()
        assert not canary.exists(), "no shell command or file write happened"
        offered = {t["name"] for t in api.requests[0]["tools"]}
        assert offered - {"DeferredToolPlaceholder"} == {f"mcp__robot__{t.name}" for t in tool_list()}
        results = [b for m in api.requests[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        refused = [r for r in results if "No such tool available" in json.dumps(r)]
        assert len(refused) == 5, "Bash, Write, Read, WebFetch and Agent were all refused by the CLI"
        assert ("go_to", {"place": "kitchen"}) in body.calls, "the allowed MCP tool did work"
        assert ("say", {"text": "I can't run commands, but I went to the kitchen."}) in body.calls
        blob = json.dumps(api.requests[0])
        assert "You are Claude, made by Anthropic" in blob, "our system prompt replaced Claude Code's"
        assert "# Global Rules" not in blob and "MANDATORY BACKUP" not in blob, "Nick's CLAUDE.md didn't load"


@needs_cli
async def test_real_cli_photo_reaches_the_model_but_never_the_disk(mind_cfg, clock, tmp_path):
    script = [[{"type": "tool_use", "name": "mcp__robot__look", "input": {"at": "ahead"}}],
              [{"type": "text", "text": "A shiny beetle."}]]
    with FakeAnthropicAPI(script) as api:
        cfg = offline_cfg(mind_cfg, tmp_path, api)
        engine, body, _ = make_engine(cfg, clock, FakeClaude(), body=robot_body())
        try:
            await engine.run_turn([heard("what's this bug?")])
        finally:
            await engine.cc.close()
        images = [c for m in api.requests[-1]["messages"] if isinstance(m["content"], list)
                  for b in m["content"] if b.get("type") == "tool_result" and isinstance(b.get("content"), list)
                  for c in b["content"] if c.get("type") == "image"]
        assert images and images[0]["source"]["data"] == JPEG_B64
    from tests.test_privacy_and_cost import assert_no_image_data
    assert_no_image_data(cfg.claude_code.work_dir, cfg.state_dir, cfg.memory_dir)
