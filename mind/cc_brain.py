"""The `claude_code` brain: one long-lived, locked-down Claude Code process.

Instead of calling the Claude API directly, the mind can drive a `claude` CLI
process logged in to a Claude plan (config: brain = "claude_code"). The engine
doesn't change: the same events go in (heard / touch / event / timer), and the
same tool calls come out to the body. Only the "thinking" part moves.

How it fits together:

    Engine.run_turn ──user message (stream-json)──► claude -p (one process, kept running)
          ▲                                             │ calls mcp__robot__<tool>
          │ spoken text, usage (stream-json)            ▼
          │                                      python -m mind.cc_mcp (MCP server, child of claude)
          │                                             │ unix socket (0600, per-run token)
          └────────────── ToolBridge ◄──────────────────┘ → Engine.run_tool → body / memory / house

Locked down (each of these was checked against the real CLI, see tests/):
  - `--tools ""`               no built-in tools at all: no Bash, Read, Write, Edit,
                               Glob, Grep, WebFetch, WebSearch, Task/Agent, ...
  - `--allowedTools`           only the robot's MCP tools; `--disallowedTools` lists
                               the built-ins too, as a second lock
  - `--strict-mcp-config`      only our MCP server, never Nick's
  - `--setting-sources ""`     no user/project/local settings files
  - `--permission-mode dontAsk` + `--permission-prompts none`: anything not
                               allowed is refused, nobody is asked
  - `--no-session-persistence` the CLI saves no transcript (photos stay in RAM)
  - `--system-prompt`          our prompts/system.md replaces Claude Code's own
  - env CLAUDE_CODE_DISABLE_CLAUDE_MDS / _AUTO_MEMORY: no CLAUDE.md, no auto-memory
  - HOME and CLAUDE_CONFIG_DIR point inside state/cc-brain/, so nothing reads
    or writes ~/.claude; the environment is built from scratch, so the mind's
    own secrets (ANTHROPIC_API_KEY, HA_TOKEN, BODY_TOKEN) are never passed on
  - auth is CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`), so the run is
    on the plan, never on API billing

If the process dies, the turn in progress fails (the robot says it's foggy) and
the next turn starts a fresh process, seeded with a text transcript of earlier
today, the same as a mind restart. The CLI's own --resume is NOT used: it would
need the transcript (with photos) saved to disk.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .config import PROJECT_DIR, MindConfig
from .tools import mcp_tools

log = logging.getLogger(__name__)

MCP_SERVER = "robot"
# Listed as well as `--tools ""`, as a second lock in case a CLI update changes defaults.
DISALLOWED_BUILTINS = [
    "Bash", "BashOutput", "KillShell", "PowerShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "NotebookRead", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
    "Skill", "SlashCommand", "ExitPlanMode", "Monitor", "Workflow",
]


class BrainCrashed(RuntimeError):
    pass


def isolated_env(cc, root: Path) -> dict:
    """The environment for every `claude` process we start. Built from scratch:
    nothing from the mind's own environment leaks in except the plan token
    (and test-only extras from config)."""
    exe_dir = str(Path(shutil.which(cc.executable) or cc.executable).parent)
    env = {
        "PATH": f"{exe_dir}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(root / "home"),
        "CLAUDE_CONFIG_DIR": str(root / "config"),
        "LANG": "C.UTF-8",
        "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_AUTOUPDATER": "1",
        "MCP_TIMEOUT": "30000",
        "MCP_TOOL_TIMEOUT": "330000",
    }
    token = os.environ.get(cc.token_env, "")
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    env.update(cc.extra_env)          # tests only (e.g. a local fake API)
    return env


# The flags that switch everything off, shared by the brain and the nightly runner.
LOCKDOWN_FLAGS = [
    "--tools", "",
    "--disallowedTools", ",".join(DISALLOWED_BUILTINS),
    "--strict-mcp-config",
    "--setting-sources", "",
    "--permission-mode", "dontAsk", "--permission-prompts", "none",
    "--no-session-persistence", "--disable-slash-commands", "--no-chrome",
]


@dataclass
class TurnStats:
    first_token_s: float | None = None
    full_turn_s: float = 0.0
    usage: dict = field(default_factory=dict)
    notional_cost_usd: float = 0.0       # what this turn would have cost on the API (CLI's estimate)
    num_turns: int = 0
    permission_denials: list = field(default_factory=list)
    spoke: list[str] = field(default_factory=list)
    ok: bool = True


# ------------------------------------------------------------------- bridge
class ToolBridge:
    """A Unix-socket server in the mind. The MCP server (mind/cc_mcp.py) sends
    {"token", "name", "args"} per line; we run the tool and answer
    {"content", "is_error"} (Anthropic tool_result shape)."""

    def __init__(self, run_tool):
        self.run_tool = run_tool            # async (name, tool_use_id, args) -> tool_result block
        self.token = secrets.token_hex(16)
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        # Short path (AF_UNIX allows ~108 chars); created 0700 in start(), removed in stop().
        self.folder = Path(runtime) / f"cc-bridge-{self.token[:12]}"
        self.path = self.folder / "tools.sock"
        self.server = None
        self.calls: list[str] = []
        self._n = 0

    async def start(self) -> None:
        self.folder.mkdir(mode=0o700)
        self.server = await asyncio.start_unix_server(self._handle, path=str(self.path), limit=16 * 1024 * 1024)
        os.chmod(self.path, 0o600)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        shutil.rmtree(self.folder, ignore_errors=True)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads(await reader.readline())
            if not hmac.compare_digest(str(req.get("token", "")), self.token):
                reply = {"content": "Not allowed.", "is_error": True}
            else:
                self._n += 1
                self.calls.append(req["name"])
                block = await self.run_tool(req["name"], f"mcp-{self._n}", req.get("args") or {})
                reply = {"content": block["content"], "is_error": bool(block.get("is_error"))}
            writer.write((json.dumps(reply) + "\n").encode())
            await writer.drain()
        except Exception as e:
            log.exception("tool bridge error")
            try:
                writer.write((json.dumps({"content": f"Bridge error: {e}", "is_error": True}) + "\n").encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()


# -------------------------------------------------------------------- brain
class ClaudeCodeBrain:
    def __init__(self, cfg: MindConfig, run_tool):
        self.cfg = cfg
        self.cc = cfg.claude_code
        self.root = Path(self.cc.work_dir)
        self.bridge = ToolBridge(run_tool)
        self.proc: asyncio.subprocess.Process | None = None
        self._lines: asyncio.Queue = asyncio.Queue()
        self._reader: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self.system_prompt = ""
        self.started_for_day = None
        self.restarts = 0
        self.last_stats: TurnStats | None = None
        self._session_cost = 0.0     # the CLI reports total_cost_usd as a running total per process

    # ------------------------------------------------------------- command
    def allowed_tools(self) -> list[str]:
        return [f"mcp__{MCP_SERVER}__{t['name']}" for t in mcp_tools()]

    def mcp_config(self) -> dict:
        return {"mcpServers": {MCP_SERVER: {
            "command": sys.executable,
            "args": ["-m", "mind.cc_mcp"],
            "env": {"PYTHONPATH": str(PROJECT_DIR), "CC_BRIDGE_SOCKET": str(self.bridge.path),
                    "CC_BRIDGE_TOKEN": self.bridge.token},
        }}}

    def command(self) -> list[str]:
        return [
            self.cc.executable, "-p",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",
            "--model", self.cc.model, "--effort", self.cc.effort,
            *LOCKDOWN_FLAGS,
            "--allowedTools", ",".join(self.allowed_tools()),
            "--mcp-config", json.dumps(self.mcp_config()),
            "--system-prompt", self.system_prompt,
        ]

    def environment(self) -> dict:
        return isolated_env(self.cc, self.root)

    # ------------------------------------------------------------ process
    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self, index_text: str, day=None) -> None:
        """Start (or restart) the CLI with today's frozen system prompt."""
        await self.stop_process()
        if self.bridge.server is None:
            await self.bridge.start()
        for sub in ("home", "config", "work"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        # The CLI keeps MCP connection logs under HOME/.cache; clear them each start.
        shutil.rmtree(self.root / "home" / ".cache", ignore_errors=True)
        system_text = (PROJECT_DIR / "mind" / "prompts" / "system.md").read_text(encoding="utf-8")
        self.system_prompt = (system_text + "\n\n## Your memory index (/memories/INDEX.md), as of this morning\n\n"
                              + (index_text.strip() or "(empty)") + "\n\nUse the `memory` tool to read or change "
                              "your memory files. You have no other tools for files, commands or the web.\n")
        self._lines = asyncio.Queue()
        self._session_cost = 0.0
        self.proc = await asyncio.create_subprocess_exec(
            *self.command(), cwd=str(self.root / "work"), env=self.environment(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            limit=32 * 1024 * 1024)
        self._reader = asyncio.create_task(self._read_stdout(self.proc))
        self._stderr_task = asyncio.create_task(self._read_stderr(self.proc))
        self.started_for_day = day
        log.info("claude_code brain started (pid %s, model %s)", self.proc.pid, self.cc.model)

    async def _read_stdout(self, proc) -> None:
        while True:
            line = await proc.stdout.readline()
            if not line:
                self._lines.put_nowait(None)      # EOF: the process ended
                return
            try:
                self._lines.put_nowait(json.loads(line))
            except json.JSONDecodeError:
                log.debug("non-JSON line from claude: %.200s", line)

    async def _read_stderr(self, proc) -> None:
        while True:
            line = await proc.stderr.readline()
            if not line:
                return
            log.warning("claude stderr: %s", line.decode(errors="replace").rstrip()[:500])

    async def stop_process(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            try:
                proc.stdin.close()
                await asyncio.wait_for(proc.wait(), 5)
            except (asyncio.TimeoutError, ProcessLookupError, BrokenPipeError, ConnectionResetError):
                proc.kill()
                await proc.wait()
        for task in (self._reader, self._stderr_task):
            if task:
                task.cancel()

    async def close(self) -> None:
        await self.stop_process()
        await self.bridge.stop()

    # --------------------------------------------------------------- turn
    async def turn(self, user_text: str, on_text) -> TurnStats:
        """Send one user message; speak text as it arrives; return when the CLI
        reports the turn's result. Raises BrainCrashed if the process dies."""
        if not self.running:
            raise BrainCrashed("the claude process isn't running")
        loop = asyncio.get_running_loop()
        stats = TurnStats()
        t0 = loop.time()
        msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": user_text}]}}
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            raise BrainCrashed(f"couldn't write to claude: {e}") from e

        deadline = t0 + self.cc.turn_timeout_s
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                await self.stop_process()
                raise BrainCrashed(f"no result after {self.cc.turn_timeout_s:g} s")
            try:
                line = await asyncio.wait_for(self._lines.get(), remaining)
            except asyncio.TimeoutError:
                continue
            if line is None:
                raise BrainCrashed("the claude process exited")
            kind = line.get("type")
            if kind == "stream_event":
                ev = line.get("event", {})
                if stats.first_token_s is None and ev.get("type") == "content_block_delta":
                    stats.first_token_s = loop.time() - t0
            elif kind == "assistant":
                for block in line.get("message", {}).get("content", []):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        if stats.first_token_s is None:
                            stats.first_token_s = loop.time() - t0
                        stats.spoke.append(block["text"].strip())
                        await on_text(block["text"].strip())
            elif kind == "result":
                stats.full_turn_s = loop.time() - t0
                stats.usage = line.get("usage") or {}
                total = float(line.get("total_cost_usd") or 0.0)     # running total for this process
                stats.notional_cost_usd = round(max(0.0, total - self._session_cost), 6)
                self._session_cost = total
                stats.num_turns = int(line.get("num_turns") or 0)
                stats.permission_denials = line.get("permission_denials") or []
                stats.ok = not line.get("is_error") and line.get("subtype") == "success"
                self.last_stats = stats
                return stats


# ------------------------------------------------------------ nightly runner
class ClaudeCodeBatchRunner:
    """Stands in for the Message Batches API when the mind runs on a plan:
    NightlyJob calls create_batch / batch_ended / batch_results as usual, and
    each request runs as one locked-down `claude -p --json-schema` call (no
    tools, no MCP server, same isolated HOME). Its usage is logged as plan usage."""

    on_plan = True

    def __init__(self, cfg: MindConfig):
        self.cfg = cfg
        self.cc = cfg.claude_code
        self.root = Path(self.cc.work_dir)
        self._results: dict[str, list] = {}

    async def create_batch(self, requests: list[dict]) -> str:
        batch_id = f"ccbatch-{secrets.token_hex(6)}"
        self._results[batch_id] = [await self._run(r) for r in requests]
        return batch_id

    async def batch_ended(self, batch_id: str) -> bool:
        return True

    async def batch_results(self, batch_id: str) -> list:
        return self._results.pop(batch_id, [])

    async def _run(self, request: dict):
        from anthropic.types.messages import MessageBatchIndividualResponse

        params = request["params"]
        schema = params["output_config"]["format"]["schema"]
        for sub in ("home", "config", "work"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        cmd = [self.cc.executable, "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
               "--model", self.cc.model, "--effort", params["output_config"].get("effort", "medium"),
               *LOCKDOWN_FLAGS, "--system-prompt", params["system"]]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(self.root / "work"), env=isolated_env(self.cc, self.root),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(params["messages"][0]["content"].encode()),
                                          self.cc.turn_timeout_s * 2)
        if proc.returncode != 0:
            raise RuntimeError(f"claude exited {proc.returncode}: {err.decode(errors='replace')[:300]}")
        result = json.loads(out)
        if result.get("is_error") or result.get("structured_output") is None:
            raise RuntimeError(f"claude gave no structured output ({result.get('subtype')})")
        usage = result.get("usage") or {}
        message = {
            "id": "msg_cc_nightly", "type": "message", "role": "assistant", "model": self.cc.model,
            "content": [{"type": "text", "text": json.dumps(result["structured_output"])}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                      "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                      "cache_creation_input_tokens": usage.get("cache_creation_input_tokens")},
        }
        response = MessageBatchIndividualResponse.model_validate(
            {"custom_id": request["custom_id"], "result": {"type": "succeeded", "message": message}})
        response.notional_usd = float(result.get("total_cost_usd") or 0.0)
        return response
