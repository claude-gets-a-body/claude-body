"""Talking to the Claude API.

`chat_request()` builds every conversation request. What it sets, and why:

  model            claude-opus-5-5, from config. Never changed by code.
  thinking         {"type": "adaptive"}. On Opus 5.5 thinking is always on;
                   "disabled" or a token budget would be rejected.
  output_config    {"effort": "low"} at the top level, and it stays "low" all
                   day. When a turn becomes a multi-step task the engine raises
                   effort with an effort-only {"role": "system"} message instead
                   (beta mid-conversation-output-config-2026-07-01), because
                   changing the top-level value would throw away the cache.
  cache_control    {"type": "ephemeral", "ttl": "1h"} at the top level, so the
                   growing conversation is cached; plus an explicit 1h marker on
                   the last system block (see day.py). Family chat comes in bursts
                   with 5-60 minute gaps, which is where the 1-hour TTL pays off
                   (writes cost 2x input instead of 1.25x).
  context_management  server-side compaction (beta compact-2026-01-12): when the
                   day's conversation passes the trigger, the API summarises the
                   older part. We append the full response so the compaction
                   block is kept.
  fallbacks        "default" (beta server-side-fallback-2026-07-01): if a safety
                   classifier declines a harmless request, the API retries it on
                   the model Anthropic recommends for that case. The budget
                   governor prices that part at the fallback model's rates.

No tool_choice is sent: on Opus 5.5 forcing a tool ("any"/"tool") is a 400.
"""

from __future__ import annotations

from .config import ClaudeConfig

BETA_COMPACTION = "compact-2026-01-12"
BETA_FALLBACK = "server-side-fallback-2026-07-01"
BETA_PER_MESSAGE_EFFORT = "mid-conversation-output-config-2026-07-01"

COMPACTION_INSTRUCTIONS = (
    "Summarise the conversation so far as notes to yourself, so you can carry on "
    "naturally. You are Claude, living with a family as a small home robot. Keep: who "
    "you've talked to today and what each of them asked or cared about; anything you "
    "promised or set a timer for; tasks still in progress and where you are in them; "
    "places you've been today; anything someone asked you to remember or not to do. "
    "Leave out small talk that has no follow-up."
)


def chat_request(cfg: ClaudeConfig, system_blocks: list[dict], tools: list[dict],
                 messages: list[dict]) -> dict:
    betas = [BETA_COMPACTION, BETA_PER_MESSAGE_EFFORT]
    params = {
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "system": system_blocks,
        "tools": tools,
        "messages": messages,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": cfg.effort_chat},
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
        "context_management": {"edits": [{
            "type": "compact_20260112",
            "trigger": {"type": "input_tokens", "value": cfg.compact_trigger_tokens},
            "instructions": COMPACTION_INSTRUCTIONS,
        }]},
    }
    if cfg.use_fallbacks:
        params["fallbacks"] = "default"
        betas.append(BETA_FALLBACK)
    params["betas"] = betas
    return params


def effort_message(level: str) -> dict:
    """An effort-only system message. Takes effect from the next user message."""
    return {"role": "system", "content": [], "output_config": {"effort": level}}


class ClaudeClient:
    """The real API. Only used with `python -m mind --live`."""

    def __init__(self, api_key: str, timeout_s: float, http_client=None):
        import anthropic   # imported here so the fake path never needs a key

        # api_key is passed explicitly so the SDK can't silently pick up some
        # other credential from the environment or an `ant` profile.
        # http_client is only for tests (a fake transport, no network).
        extra = {"http_client": http_client} if http_client is not None else {}
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s, **extra)

    async def create(self, **params):
        return await self._client.beta.messages.create(**params)

    async def create_batch(self, requests: list[dict]) -> str:
        batch = await self._client.messages.batches.create(requests=requests)
        return batch.id

    async def batch_ended(self, batch_id: str) -> bool:
        batch = await self._client.messages.batches.retrieve(batch_id)
        return batch.processing_status == "ended"

    async def batch_results(self, batch_id: str) -> list:
        return [r async for r in await self._client.messages.batches.results(batch_id)]
