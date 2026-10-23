"""A pretend Claude for the simulator and the tests. No network, no API key.

It answers with real SDK objects (BetaMessage etc.), so the engine runs exactly
the code it runs against the real API. Two ways to drive it:

  - Keyword rules (the default, used by `python -m mind --fake-llm`): "look at
    this" -> calls `look`; "come here" -> `approach`; "go to the kitchen" ->
    `go_to`; "remember that ..." -> memory; "is the back door open" -> `house`;
    "remind me in 5 minutes ..." -> `timer`; anything else gets a polite echo.
  - A script: tests pass a list of responses (dicts, or functions that take the
    request and return a dict) which are used in order.

Every request is also CHECKED against the API rules this design depends on, and
any problem is recorded in `self.problems` and raised:
  - no forced tool_choice, no disabled thinking or budget_tokens
  - first message is from the user
  - a text system message follows a user message and is the last message or is
    followed by the assistant
  - every tool_use gets a tool_result in the next user message
  - history is append-only: within a day, each request starts with exactly the
    messages of the previous ANSWERED request (a request that failed with a
    network error bound nothing, like on the real API)
  - the beta headers match the features used
"""

from __future__ import annotations

import copy
import json
import re
from typing import Callable

from anthropic.types import Message
from anthropic.types.beta import BetaMessage
from anthropic.types.messages import MessageBatchIndividualResponse

from .llm import BETA_COMPACTION, BETA_FALLBACK, BETA_PER_MESSAGE_EFFORT


class FakeRequestProblem(Exception):
    pass


def usage(input_tokens=60, output_tokens=40, cache_read=4000, cache_write_1h=200, compaction=None,
          web_searches=0) -> dict:
    iterations = []
    if compaction:
        iterations.append({"type": "compaction", "input_tokens": compaction, "output_tokens": 800,
                           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
    iterations.append({"type": "message", "input_tokens": input_tokens, "output_tokens": output_tokens,
                       "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write_1h,
                       "cache_creation": {"ephemeral_1h_input_tokens": cache_write_1h,
                                          "ephemeral_5m_input_tokens": 0}})
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write_1h,
            "cache_creation": {"ephemeral_1h_input_tokens": cache_write_1h, "ephemeral_5m_input_tokens": 0},
            "server_tool_use": {"web_search_requests": web_searches, "web_fetch_requests": 0},
            "iterations": iterations}


def text_reply(text: str, **usage_kw) -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "usage": usage(**usage_kw)}


def tool_reply(name: str, tool_input: dict, text: str | None = None, tool_id: str | None = None) -> dict:
    content = []
    if text:
        content.append({"type": "text", "text": text})
    content.append({"type": "tool_use", "id": tool_id or "toolu_fake", "name": name, "input": tool_input})
    return {"content": content, "stop_reason": "tool_use", "usage": usage()}


class FakeClaude:
    def __init__(self, script: list[dict | Callable[[dict], dict]] | None = None,
                 compact_after_messages: int | None = None):
        self.script = list(script or [])
        self.requests: list[dict] = []
        self.problems: list[str] = []
        self.compact_after_messages = compact_after_messages
        self._compacted_at: int | None = None
        self._ids = 0
        self._last_answered: dict | None = None   # last request that got a response
        self.batches: dict[str, list[dict]] = {}

    # ------------------------------------------------------------ messages
    async def create(self, **params) -> BetaMessage:
        params = copy.deepcopy(params)
        self._check(params)
        self.requests.append(params)
        if self.script:
            spec = self.script.pop(0)
            spec = spec(params) if callable(spec) else copy.deepcopy(spec)   # may raise, like a network error
        else:
            spec = self._respond(params)
        self._last_answered = params
        if (self.compact_after_messages and self._compacted_at is None
                and len(params["messages"]) >= self.compact_after_messages):
            self._compacted_at = len(params["messages"])
            spec["content"].insert(0, {"type": "compaction",
                                       "content": "Summary so far: (fake) the family chatted with Claude."})
            spec["usage"] = usage(compaction=150_000)
        return self._message(spec)

    def _message(self, spec: dict) -> BetaMessage:
        self._ids += 1
        for block in spec["content"]:
            if block["type"] == "tool_use" and block["id"] == "toolu_fake":
                block["id"] = f"toolu_fake{self._ids}"
        return BetaMessage.model_validate({
            "id": f"msg_fake{self._ids}", "type": "message", "role": "assistant",
            "model": "claude-opus-5-5", "stop_sequence": None, **spec})

    # ------------------------------------------------------- the checks
    def _problem(self, text: str) -> None:
        self.problems.append(text)
        raise FakeRequestProblem(text)

    def _check(self, p: dict) -> None:
        betas = set(p.get("betas", []))
        if p.get("tool_choice", {}).get("type") in ("any", "tool"):
            self._problem("forced tool_choice is a 400 on claude-opus-5-5")
        thinking = p.get("thinking") or {}
        if thinking.get("type") in ("disabled", "enabled") or "budget_tokens" in thinking:
            self._problem("thinking must be adaptive (or omitted) on claude-opus-5-5")
        if p.get("fallbacks") == "default" and BETA_FALLBACK not in betas:
            self._problem("fallbacks='default' needs the server-side-fallback-2026-07-01 beta")
        if p.get("context_management") and BETA_COMPACTION not in betas:
            self._problem("compaction needs the compact-2026-01-12 beta")

        msgs = p["messages"]
        if not msgs or msgs[0]["role"] != "user":
            self._problem("the first message must be from the user")
        for i, m in enumerate(msgs):
            if m["role"] != "system":
                continue
            effort_only = m.get("content") == [] and "output_config" in m
            if effort_only:
                if BETA_PER_MESSAGE_EFFORT not in betas:
                    self._problem("per-message effort needs the mid-conversation-output-config beta")
                continue
            prev = next((x for x in reversed(msgs[:i]) if not (x["role"] == "system" and x.get("content") == [])),
                        None)
            if prev is None or prev["role"] != "user":
                self._problem(f"system message {i} must follow a user message")
            nxt = next((x for x in msgs[i + 1:] if not (x["role"] == "system" and x.get("content") == [])), None)
            if nxt is not None and nxt["role"] != "assistant":
                self._problem(f"system message {i} must be last or followed by the assistant")
        for i, m in enumerate(msgs):
            if m["role"] != "assistant" or not isinstance(m["content"], list):
                continue
            ids = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
            if not ids:
                continue
            nxt = next((x for x in msgs[i + 1:] if x["role"] != "system"), None)
            if nxt is None:
                self._problem(f"assistant message {i} called tools but no results were sent")
            got = {b.get("tool_use_id") for b in nxt["content"]} if isinstance(nxt["content"], list) else set()
            if not ids <= got:
                self._problem(f"tool_use ids {ids - got} have no tool_result")

        # Only requests that got an answer matter: a failed request bound nothing.
        if self._last_answered is not None:
            prev = self._last_answered
            same_conversation = (prev["system"] == p["system"] and prev["tools"] == p["tools"]
                                 and prev["messages"][:1] == p["messages"][:1])
            if same_conversation:
                n = len(prev["messages"])
                if p["messages"][:n] != prev["messages"]:
                    self._problem("history was edited: this request doesn't start with the previous one")

    # ------------------------------------------------------------- rules
    @staticmethod
    def _last_heard(params: dict) -> tuple[str, str]:
        """(speaker, text) from the newest user text message."""
        for m in reversed(params["messages"]):
            if m["role"] == "user" and isinstance(m["content"], str):
                found = re.findall(r'\[heard\] (.+?): "(.*)"', m["content"])
                if found:
                    return found[-1]
                return "", m["content"]
        return "", ""

    def _tool_names(self, params: dict) -> dict[str, str]:
        names = {}
        for m in params["messages"]:
            if m["role"] == "assistant" and isinstance(m["content"], list):
                for b in m["content"]:
                    if b.get("type") == "tool_use":
                        names[b["id"]] = b["name"]
        return names

    def _respond(self, params: dict) -> dict:
        last = next(m for m in reversed(params["messages"]) if m["role"] != "system")
        if last["role"] == "user" and isinstance(last["content"], list):
            return self._after_tools(params, last["content"])
        speaker, said = self._last_heard(params)
        if said.startswith("[touch]"):
            return text_reply("Hehe, that tickles!")
        if said.startswith("[timer]"):
            return text_reply("Reminder! " + said.split(":", 1)[-1].strip())
        if said.startswith("[event]"):
            return tool_reply("express", {"mood": "surprised"}, "Whoops!")
        return self._rules(speaker, said)

    def _rules(self, speaker: str, said: str) -> dict:
        s = said.lower()
        if "stop looking" in s or s.strip(" .!") == "stop":
            return text_reply("Okay.")
        if m := re.search(r"remind me in (\d+) ?min\w* (?:to )?(.*)", s):
            return tool_reply("timer", {"minutes": int(m.group(1)), "note": m.group(2) or "reminder",
                                        "for_person": speaker or None}, "Sure.")
        if "remember that" in s:
            fact = said[s.index("remember that") + len("remember that"):].strip(" .")
            return tool_reply("memory", {"command": "create", "path": f"/memories/notes/fake-{self._ids + 1}.md",
                                         "file_text": f"{speaker or 'someone'} told me: {fact}\n"})
        if any(k in s for k in ("what did", "last time", "do you remember")):
            return tool_reply("recall", {"query": said})
        if any(k in s for k in ("door", "window", "temperature", "warm", "cold", "raining")):
            return tool_reply("house", {"question": said})
        if any(k in s for k in ("look", "what's this", "what is this", "can you see")):
            return tool_reply("look", {"at": "ahead"}, "Let me have a look.")
        if "come here" in s or "come to me" in s:
            return tool_reply("approach", {}, "Coming!")
        if m := re.search(r"go (?:to|into) (?:the )?([a-z' ]+)", s):
            return tool_reply("go_to", {"place": m.group(1).strip()}, "On my way.")
        if any(k in s for k in ("dock", "go to bed", "charge")):
            return tool_reply("dock", {}, "Heading to my dock.")
        if "goodnight" in s or "go to sleep" in s:
            return tool_reply("sleep", {}, "Goodnight!")
        if "turn around" in s or "look at me" in s:
            return tool_reply("turn_to", {"target": "speaker"})
        who = speaker if speaker and speaker != "someone" else "you"
        return text_reply(f'(fake Claude) I heard {who} say: "{said}". What should we do next?')

    def _after_tools(self, params: dict, results: list[dict]) -> dict:
        names = self._tool_names(params)
        replies = []
        for r in results:
            if r.get("type") != "tool_result":
                continue
            name = names.get(r.get("tool_use_id"), "?")
            content = r.get("content")
            if isinstance(content, list):
                images = [c for c in content if c.get("type") == "image"]
                text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
                if images:
                    kb = len(images[0]["source"]["data"]) * 3 // 4 // 1024
                    replies.append(f"I can see it now. (fake Claude: got a {kb} KB photo.)")
                    continue
                content = text
            content = str(content)
            if r.get("is_error"):
                replies.append(f"Hmm, I couldn't do that: {content}")
            elif name == "house":
                replies.append("Home Assistant says: " + content.splitlines()[0])
            elif name == "recall":
                replies.append(content.splitlines()[0])
            elif name == "memory":
                replies.append("Got it, I'll remember that.")
            elif name == "timer":
                replies.append("Okay! " + content)
            elif name in ("go_to", "approach", "dock"):
                replies.append("Here I am!" if name != "dock" else "Docked.")
            elif name in ("express", "turn_to", "say", "sleep", "stop"):
                pass
            else:
                replies.append("Done.")
        return text_reply(" ".join(replies) or QUIET)

    # -------------------------------------------------------------- batches
    async def create_batch(self, requests: list[dict]) -> str:
        batch_id = f"msgbatch_fake{len(self.batches) + 1}"
        self.batches[batch_id] = copy.deepcopy(requests)
        return batch_id

    async def batch_ended(self, batch_id: str) -> bool:
        return True

    async def batch_results(self, batch_id: str) -> list:
        out = []
        for req in self.batches[batch_id]:
            day = req["custom_id"].removeprefix("diary-")
            transcript = req["params"]["messages"][0]["content"]
            lines = transcript.split("## Transcript", 1)[-1].split("## Current memory files", 1)[0].strip()
            n = len([x for x in lines.splitlines() if x.strip()])
            answer = {"diary": f"# {day}\n\n(fake diary) I had {n} lines of conversation today.",
                      "file_updates": [{"path": "/memories/promises.md",
                                        "content": f"# Promises\n\n- (fake) checked on {day}\n"}]}
            message = Message.model_validate({
                "id": "msg_fakebatch", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": json.dumps(answer)}], "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 3000, "output_tokens": 600, "service_tier": "batch"}})
            out.append(MessageBatchIndividualResponse.model_validate(
                {"custom_id": req["custom_id"], "result": {"type": "succeeded", "message": message.to_dict()}}))
        return out


QUIET = "[quiet]"
