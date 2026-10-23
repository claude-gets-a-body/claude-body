#!/usr/bin/env python3
"""A pretend `claude` CLI for unit tests of the claude_code brain.

It speaks the same stream-json as the real CLI (checked against claude 2.1.309,
see tests/test_cc_brain.py), and it is a real MCP client: it starts the MCP
server named in --mcp-config and calls the robot's tools through it, so a test
exercises the whole chain (MCP server -> bridge -> engine -> body).

It records its command line and environment variable NAMES (never values) to
the file in $FAKE_CLAUDE_RECORD, so tests can check the lockdown flags.

What it "says", by keyword in the newest user message:
    look      -> calls mcp__robot__look, reports the photo size
    go to X   -> calls mcp__robot__go_to {"place": X}
    remember  -> calls mcp__robot__memory (create /memories/people/sam.md)
    run ls    -> pretends the model asked for Bash; the "CLI" refuses, like the real one
    crash     -> exits without a result
    otherwise -> a short echo
With --json-schema (the nightly job) it prints one JSON result with a diary.
"""

import asyncio
import json
import os
import re
import sys


def emit(obj) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def arg_after(flag: str, default=None):
    argv = sys.argv
    return argv[argv.index(flag) + 1] if flag in argv else default


def record() -> None:
    path = os.environ.get("FAKE_CLAUDE_RECORD")
    if path:
        with open(path, "a") as f:
            f.write(json.dumps({"argv": sys.argv[1:], "env_names": sorted(os.environ), "cwd": os.getcwd(),
                                "home": os.environ.get("HOME"), "config": os.environ.get("CLAUDE_CONFIG_DIR")}) + "\n")


USAGE = {"input_tokens": 120, "output_tokens": 30, "cache_read_input_tokens": 9000,
         "cache_creation_input_tokens": 500, "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0}}


def say(text: str) -> None:
    emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "text_delta", "text": text[:5]}}})
    emit({"type": "assistant", "message": {"id": "msg_fake", "role": "assistant", "type": "message",
                                           "content": [{"type": "text", "text": text}]}})


async def chat(session, tools: list[str]) -> None:
    emit({"type": "system", "subtype": "init", "tools": tools, "mcp_servers": [{"name": "robot", "status": "connected"}],
          "model": arg_after("--model"), "permissionMode": arg_after("--permission-mode")})
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=32 * 1024 * 1024)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    turns = 0
    while True:
        line = await reader.readline()
        if not line:
            return
        msg = json.loads(line)
        text = " ".join(b.get("text", "") for b in msg["message"]["content"])
        heard = text.split("[end of context]")[-1]
        seeded = "[earlier today" in heard
        heard = heard.split("[end of transcript]")[-1].lower()     # only the newest words, not the seed
        turns += 1
        calls = 1
        if "crash" in heard:
            os._exit(3)
        elif "run ls" in heard:
            emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                                "input": {"command": "ls"}}]}})
            allowed = arg_after("--allowedTools", "")
            if "Bash" not in allowed.split(",") or arg_after("--tools") == "":
                emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                      "content": "<tool_use_error>Error: No such tool available: Bash.</tool_use_error>"}]}})
                say("I can't run commands, I'm a robot!")
            calls = 2
        elif "look" in heard:
            result = await session.call_tool("look", {"at": "ahead"})
            images = [c for c in result.content if getattr(c, "type", "") == "image"]
            size = len(images[0].data) * 3 // 4 if images else 0
            say(f"I can see it: a {size} byte photo." if images else "My camera didn't work.")
            calls = 2
        elif m := re.search(r"go to (?:the )?([a-z ]+)", heard):
            result = await session.call_tool("go_to", {"place": m.group(1).strip()})
            say(("Sorry: " if result.is_error else "Done: ") + result.content[0].text)
            calls = 2
        elif "remember" in heard:
            result = await session.call_tool("memory", {"command": "create", "path": "/memories/people/sam.md",
                                                        "file_text": "# Sam\n- likes dinosaurs\n"})
            say("Got it." if not result.is_error else "Couldn't save that.")
            calls = 2
        else:
            say(f"{'(seeded) ' if seeded else ''}(fake claude) you said: {heard.strip()[:80]}")
        emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": calls, "result": "",
              # like the real CLI, total_cost_usd is a running total for the process
              "usage": USAGE, "total_cost_usd": round(0.0123 * turns, 4), "permission_denials": [], "duration_ms": 10})


async def main() -> None:
    record()
    if "--json-schema" in sys.argv:            # the nightly job
        sys.stdin.read()
        emit({"type": "result", "subtype": "success", "is_error": False,
              "structured_output": {"diary": "# Fake diary\n\nA nice day.", "file_updates": []},
              "usage": USAGE, "total_cost_usd": 0.02})
        return

    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server = json.loads(arg_after("--mcp-config"))["mcpServers"]["robot"]
    params = StdioServerParameters(command=server["command"], args=server["args"], env=server.get("env"))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            await chat(session, [f"mcp__robot__{t.name}" for t in listed.tools])


if __name__ == "__main__":
    asyncio.run(main())
