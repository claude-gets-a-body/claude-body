"""The robot's tools as an MCP server, for the claude_code brain.

The `claude` CLI starts this as a child process (stdio MCP transport) and offers
its tools to the model as mcp__robot__<name>. This server does no work itself:
every call is forwarded over a private Unix socket to the mind process, which
runs it with exactly the same code as the API brain (Engine.run_tool). So a
body tool still becomes a `tool_call` to the robot, memory still goes through
MemoryStore's path checks, and `house` is still GET-only.

    claude CLI --stdio--> this server --unix socket--> mind (Engine.run_tool)

Environment (set by mind/cc_brain.py in the MCP config):
    CC_BRIDGE_SOCKET   path of the mind's Unix socket (mode 0600)
    CC_BRIDGE_TOKEN    shared secret for this mind process

Results come back in the Anthropic tool_result shape and are converted to MCP
content: text -> TextContent, a `look` photo -> ImageContent (JPEG, base64).
No file is ever written.

Run by hand only for debugging:  python -m mind.cc_mcp
"""

from __future__ import annotations

import asyncio
import json
import os

import mcp_types as types
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

from mind.tools import mcp_tools

SERVER_NAME = "robot"
BRIDGE_TIMEOUT_S = 330.0     # longer than the longest body tool (dock: 300 s)


def tool_list() -> list[types.Tool]:
    return [types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
            for t in mcp_tools()]


def to_mcp_content(content) -> list:
    """Anthropic tool_result content (a string, or a list of text/image blocks) -> MCP content."""
    if isinstance(content, str):
        return [types.TextContent(type="text", text=content)]
    out = []
    for block in content or []:
        if block.get("type") == "image":
            src = block.get("source", {})
            out.append(types.ImageContent(type="image", data=src.get("data", ""),
                                          mime_type=src.get("media_type", "image/jpeg")))
        else:
            out.append(types.TextContent(type="text", text=str(block.get("text", ""))))
    return out


async def forward(name: str, arguments: dict) -> dict:
    """Ask the mind to run one tool. Returns {"content": ..., "is_error": bool}."""
    socket_path = os.environ["CC_BRIDGE_SOCKET"]
    token = os.environ["CC_BRIDGE_TOKEN"]
    reader, writer = await asyncio.open_unix_connection(socket_path, limit=16 * 1024 * 1024)
    try:
        writer.write((json.dumps({"token": token, "name": name, "args": arguments}) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), BRIDGE_TIMEOUT_S)
        return json.loads(line)
    finally:
        writer.close()


async def on_list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(tools=tool_list())


async def on_call_tool(ctx, params) -> types.CallToolResult:
    known = {t["name"] for t in mcp_tools()}
    if params.name not in known:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"Unknown tool {params.name!r}.")],
                                    is_error=True)
    try:
        reply = await forward(params.name, dict(params.arguments or {}))
    except (OSError, asyncio.TimeoutError, json.JSONDecodeError) as e:
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"The mind didn't answer: {e}")],
                                    is_error=True)
    return types.CallToolResult(content=to_mcp_content(reply.get("content")), is_error=bool(reply.get("is_error")))


def build_server() -> Server:
    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def main() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
