"""The --live client, checked WITHOUT the network: the real anthropic SDK sends
our request through a fake HTTP transport, and we inspect exactly what would
have gone to api.anthropic.com. No API key is used or needed."""

import json

import anthropic
import httpx2

from mind.llm import ClaudeClient
from tests.conftest import heard, make_engine

CANNED_RESPONSE = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
    "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "text", "text": "Hello from the mock."}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 12, "output_tokens": 5, "cache_read_input_tokens": 0,
              "cache_creation_input_tokens": 3000,
              "cache_creation": {"ephemeral_1h_input_tokens": 3000, "ephemeral_5m_input_tokens": 0},
              "iterations": [{"type": "message", "input_tokens": 12, "output_tokens": 5,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 3000}]},
}


async def test_live_client_request_body_and_headers(mind_cfg, clock):
    captured = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.append(request)
        return httpx2.Response(200, json=CANNED_RESPONSE)

    http = anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler))
    client = ClaudeClient(api_key="sk-test-not-real", timeout_s=5, http_client=http)
    engine, body, budget = make_engine(mind_cfg, clock, client)
    await engine.run_turn([heard("hello")])

    assert len(captured) == 1
    req = captured[0]
    assert req.url.host == "api.anthropic.com" and req.url.path == "/v1/messages"
    betas = req.headers["anthropic-beta"].split(",")
    assert {"compact-2026-01-12", "server-side-fallback-2026-07-01",
            "mid-conversation-output-config-2026-07-01"} <= set(betas)
    sent = json.loads(req.content)
    assert sent["model"] == "claude-opus-5-5"
    assert sent["fallbacks"] == "default"
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["messages"][1]["role"] == "system"            # mid-conversation system message survives the SDK
    assert sent["tools"][-1]["type"] == "web_search_20260209"
    assert "budget_tokens" not in json.dumps(sent) and "tool_choice" not in sent

    # the reply (thinking block included) is stored exactly, then spoken
    assert engine.day.messages[-1] == {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "Hello from the mock."}]}
    assert body.calls[-1] == ("say", {"text": "Hello from the mock."})
    assert budget.spent_this_month() > 0
