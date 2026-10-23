"""A pretend Anthropic Messages API on 127.0.0.1, for testing the real `claude` CLI
offline. The CLI is pointed at it with ANTHROPIC_BASE_URL and a dummy API key,
so nothing reaches the internet and no real account is used.

It records every request body (headers are NOT kept: they'd hold credentials)
and answers /v1/messages from a script. Each scripted reply is a list of
content blocks, e.g.
    [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
    [{"type": "text", "text": "Hello"}]
streamed back as server-sent events the way the real API does. When the script
runs out it answers with a plain "ok".
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAnthropicAPI:
    def __init__(self, script: list[list[dict]] | None = None):
        self.script = list(script or [])
        self.requests: list[dict] = []        # bodies of POST /v1/messages
        self.other_paths: list[str] = []      # anything else the CLI asked for
        self._ids = 0
        self._lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):     # keep test output quiet
                pass

            def do_GET(self):
                api.other_paths.append(f"GET {self.path}")
                self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "fake"}})

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                path = self.path.split("?")[0]
                if path == "/v1/messages/count_tokens":
                    api.other_paths.append(f"POST {path}")
                    self._json(200, {"input_tokens": 100})
                    return
                if path != "/v1/messages":
                    api.other_paths.append(f"POST {path}")
                    self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "fake"}})
                    return
                with api._lock:
                    api.requests.append(body)
                    blocks = api.script.pop(0) if api.script else [{"type": "text", "text": "ok"}]
                    api._ids += 1
                    n = api._ids
                if body.get("stream"):
                    self._stream(blocks, n)
                else:
                    self._json(200, api.message(blocks, n))

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _event(self, name, obj):
                self.wfile.write(f"event: {name}\ndata: {json.dumps(obj)}\n\n".encode())

            def _stream(self, blocks, n):
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                msg = api.message([], n)
                msg["stop_reason"] = None
                self._event("message_start", {"type": "message_start", "message": msg})
                stop = "end_turn"
                for i, b in enumerate(blocks):
                    if b["type"] == "tool_use":
                        stop = "tool_use"
                        start = {"type": "tool_use", "id": b.get("id", f"toolu_fake{n}_{i}"), "name": b["name"], "input": {}}
                        self._event("content_block_start", {"type": "content_block_start", "index": i, "content_block": start})
                        self._event("content_block_delta", {"type": "content_block_delta", "index": i,
                                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}})
                    else:
                        self._event("content_block_start", {"type": "content_block_start", "index": i,
                                    "content_block": {"type": "text", "text": ""}})
                        self._event("content_block_delta", {"type": "content_block_delta", "index": i,
                                    "delta": {"type": "text_delta", "text": b["text"]}})
                    self._event("content_block_stop", {"type": "content_block_stop", "index": i})
                self._event("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                            "usage": {"output_tokens": 7}})
                self._event("message_stop", {"type": "message_stop"})
                self.wfile.flush()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def message(self, blocks: list[dict], n: int) -> dict:
        content = []
        for i, b in enumerate(blocks):
            if b["type"] == "tool_use":
                content.append({"type": "tool_use", "id": b.get("id", f"toolu_fake{n}_{i}"), "name": b["name"],
                                "input": b["input"]})
            else:
                content.append({"type": "text", "text": b["text"]})
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        return {"id": f"msg_fake{n}", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": content, "stop_reason": stop, "stop_sequence": None,
                "usage": {"input_tokens": 50, "output_tokens": 7, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 0}}

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
