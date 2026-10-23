"""The conversation engine: turns what the body hears and feels into Claude turns.

Flow of one turn:

    body sends `heard` / `touch` / `event` (or a timer comes due)
      -> queued; anything else that arrives while Claude is busy waits its turn
      -> engine adds a user message ("[heard] Sam: ...") and a system note
         (time, who's visible, battery, budget) to the END of today's history
      -> one request to Claude
      -> Claude's reply (the whole response.content) is appended to history
      -> any text is spoken through the body's `say`
      -> any tool calls are run: body tools go over the WebSocket as `tool_call`
         and we wait for `tool_result`; memory/recall/house/timer run here
      -> results go back to Claude in one user message; repeat until Claude
         stops calling tools (at most MAX_ROUNDS times)

History is append-only and lives in RAM (see day.py). Photos are never written
to disk, and a restarted mind starts a fresh segment seeded with a text
transcript instead of replaying a saved history.

Cost guards here: utterances with low speech-to-text confidence are ignored (no
API call), head pats start a turn at most every 30 s, and a repeated identical
body event never starts a second turn.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from common.clock import Clock, day_key, friendly_time, in_window

from .budget import BudgetGovernor
from .cc_brain import BrainCrashed, ClaudeCodeBrain
from .config import MindConfig
from .day import DayConversation, block_to_dict
from .house import HouseReader
from .llm import chat_request, effort_message
from .memory_tool import MemoryStore
from .timers import Timers
from .tools import BODY_TOOL_NAMES, all_tools
from .transcripts import TranscriptStore

log = logging.getLogger(__name__)

MAX_ROUNDS = 12          # tool-use rounds per turn, a runaway guard
QUIET_REPLY = "[quiet]"
# A turn counts as a multi-step "task" (worth effort_task instead of effort_chat)
# when Claude starts driving, or when it comes back for a second round of tools.
# One quick lookup (house, recall, memory, timer, look) stays at chat effort.
TASK_TOOLS = {"go_to", "approach", "dock", "turn_to"}

CANNED = {
    "api_error": "Sorry, my thinking's gone a bit foggy. Can you say that again in a minute?",
    "refusal": "I'd better not help with that one. Maybe ask a grown-up?",
    "over_budget": "I've used up all my words for this month, so I'm being very quiet until it resets.",
    "cut_off": "Sorry, I lost my train of thought. Can you ask me again?",
}


class BodyPort(Protocol):
    """What the engine needs from the WebSocket side (server.BodyLink)."""
    connected: bool

    async def call_tool(self, name: str, args: dict, timeout: float) -> dict: ...
    async def send(self, msg: dict) -> None: ...


@dataclass
class World:
    """The latest the body has told us. Fed into the system notes."""
    people: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    recent_events: list[str] = field(default_factory=list)
    last_touch_turn: datetime | None = None
    event_turns: dict = field(default_factory=dict)   # (e, detail) -> when it last started a turn


@dataclass
class Input:
    kind: str        # heard / touch / event / timer
    data: dict


class Engine:
    def __init__(self, cfg: MindConfig, llm, body: BodyPort, memory: MemoryStore,
                 transcripts: TranscriptStore, house: HouseReader, timers: Timers,
                 budget: BudgetGovernor, clock: Clock, system_text: str):
        self.cfg = cfg
        self.llm = llm
        self.body = body
        self.memory = memory
        self.transcripts = transcripts
        self.house = house
        self.timers = timers
        self.budget = budget
        self.clock = clock
        self.system_text = system_text
        self.tools = all_tools(memory.to_dict(), cfg.claude.web_search_max_uses)
        self.world = World()
        self.queue: asyncio.Queue[Input] = asyncio.Queue()
        self.day: DayConversation | None = None
        self.days_dir = Path(cfg.state_dir) / "days"
        self.turns_done = 0
        self.busy = asyncio.Event()     # set while a turn is running (tests use it)
        self.cc = ClaudeCodeBrain(cfg, self.run_tool) if cfg.brain == "claude_code" else None

    # ================================================================ inputs
    def on_body_message(self, msg: dict) -> None:
        """Called by the server for every message from the body (except tool_result)."""
        t = msg["t"]
        if t == "heard":
            conf = msg.get("conf")
            if isinstance(conf, (int, float)) and conf < self.cfg.min_stt_conf:
                log.info("ignoring low-confidence speech (%.2f < %.2f), no API call", conf, self.cfg.min_stt_conf)
                if msg.get("handled"):
                    self._note_event(f"your body obeyed '{msg['handled']}' (speech was unclear)")
                return
            self.queue.put_nowait(Input("heard", msg))
        elif t == "touch":
            now = self.clock.now()
            last = self.world.last_touch_turn
            if last is None or (now - last).total_seconds() >= self.cfg.touch_turn_min_gap_s:
                self.world.last_touch_turn = now
                self.queue.put_nowait(Input("touch", msg))
        elif t == "event":
            name = msg.get("e", "")
            key = (name, msg.get("detail"))
            now = self.clock.now()
            last = self.world.event_turns.get(key)
            repeat = last is not None and (now - last).total_seconds() < self.cfg.event_repeat_s
            if name in self.cfg.events_that_start_a_turn and not repeat:
                self.world.event_turns[key] = now
                self.queue.put_nowait(Input("event", msg))
            else:
                self._note_event(name)
        elif t == "saw":
            self.world.people = msg.get("people", [])
        elif t == "state":
            self.world.state = {k: v for k, v in msg.items() if k != "t"}
        elif t == "hello":
            log.info("body %s connected, can do: %s", msg.get("body_id"), msg.get("caps"))

    def _note_event(self, text: str) -> None:
        """Mention something in the next system note instead of starting a turn."""
        self.world.recent_events.append(text)
        self.world.recent_events = self.world.recent_events[-5:]

    async def run(self) -> None:
        """Main loop: one turn at a time, plus a timer checker."""
        timer_task = asyncio.create_task(self._timer_loop())
        try:
            while True:
                first = await self.queue.get()
                batch = [first]
                while not self.queue.empty():
                    batch.append(self.queue.get_nowait())
                self.busy.set()
                try:
                    await self.run_turn(batch)
                except Exception:
                    log.exception("turn failed")
                finally:
                    self.turns_done += 1
                    self.busy.clear()
        finally:
            timer_task.cancel()

    async def _timer_loop(self) -> None:
        while True:
            for t in self.timers.due():
                self.queue.put_nowait(Input("timer", t))
            await asyncio.sleep(5)

    # ======================================================== day handling
    def current_day(self) -> DayConversation:
        """Today's conversation segment. A new segment starts when the day rolls
        over, and when the mind (re)starts — then it's seeded with a text
        transcript of anything said earlier today, never a replayed history."""
        key = day_key(self.clock.now(), self.cfg.day_starts_at)
        if self.day is None or self.day.day != key:
            index = self.memory.read_text("/memories/INDEX.md")
            seed = self.transcripts.excerpt(key)
            self.day = DayConversation(self.days_dir, key, self.system_text, index, seed_text=seed)
            log.info("conversation day %s, segment %d%s", key, self.day.segment,
                     " (seeded from earlier today)" if seed else "")
        return self.day

    @staticmethod
    def current_effort(day: DayConversation) -> str | None:
        """The effort set by the latest effort-only system message, if any."""
        for m in reversed(day.messages):
            if m.get("role") == "system" and isinstance(m.get("output_config"), dict):
                return m["output_config"].get("effort")
        return None

    # ======================================================= message text
    def render_input(self, item: Input) -> str:
        d = item.data
        if item.kind == "heard":
            who = d.get("speaker") or "someone"
            text = f'[heard] {who}: "{d.get("text", "")}"'
            doa = d.get("doa")
            if isinstance(doa, (int, float)):
                side = "ahead" if abs(doa) < 20 else (f"{abs(doa):.0f}° to your left" if doa > 0
                                                       else f"{abs(doa):.0f}° to your right")
                text += f" (voice from {side})"
            if d.get("handled"):
                text += f" — your body already obeyed '{d['handled']}'."
            return text
        if item.kind == "touch":
            gesture = {"pat": "gave you a head pat", "hold": "is holding your head",
                       "double": "tapped your head twice"}.get(d.get("g"), "touched your head")
            return f"[touch] Someone {gesture}."
        if item.kind == "event":
            detail = f" ({d['detail']})" if d.get("detail") else ""
            return f"[event] {d.get('e')}{detail}"
        if item.kind == "timer":
            who = f" for {d['for_person']}" if d.get("for_person") else ""
            return f"[timer] Reminder due now{who}: {d.get('note')}"
        return f"[{item.kind}] {json.dumps(d)}"

    def context_note(self, day: DayConversation) -> str:
        now = self.clock.now()
        lines = [f"Context update: it's {friendly_time(now)}."]
        # People come from the lidar, not the camera: nobody is "seen" or named.
        if self.world.people:
            sensed = []
            for p in self.world.people:
                where = p.get("bearing", 0)
                side = "ahead" if abs(where) < 20 else ("to your left" if where > 0 else "to your right")
                sensed.append(f"a person {p.get('dist_m', '?')} m {side}")
            lines.append("Your lidar senses " + "; ".join(sensed) + ". (Your visor is down: you can't see them.)")
        else:
            lines.append("Your lidar senses nobody nearby.")
        s = self.world.state
        if s:
            bits = [f"battery {s.get('battery_pct', '?')}%"]
            bits.append("docked" if s.get("docked") else ("charging" if s.get("charging") else "not docked"))
            if s.get("place") and s.get("place") != "dock":
                bits.append(f"you're in the {s['place']}")
            if s.get("fault"):
                bits.append(f"motion blocked: {s['fault']}")
            lines.append("Body: " + ", ".join(bits) + ".")
        quiet = s.get("quiet_hours") if s else in_window(now, "21:00", "07:00")
        if quiet:
            lines.append("It's quiet hours: people may be asleep. Stay docked, speak softly and briefly.")
        if self.world.recent_events:
            lines.append("Recent body events: " + ", ".join(self.world.recent_events) + ".")
            self.world.recent_events = []
        if day.is_new and day.seed_text:
            lines.append("Your mind just restarted, so this is a fresh conversation. The first message "
                         "starts with a transcript of what was said earlier today.")
        elif day.is_new:
            yesterday = (day.day - timedelta(days=1)).isoformat()
            lines.append(f"This is the first conversation of a new day. Yesterday's diary, if it was "
                         f"written, is /memories/diary/{yesterday}.md.")
        if day.web_searches >= self.cfg.claude.web_search_max_uses:
            lines.append(f"You've used today's {self.cfg.claude.web_search_max_uses} web searches; "
                         "don't search again today.")
        status = self.budget.status()
        if status.level in ("brief", "over") and not self._has_note(day, "Budget: brief"):
            lines.append(f"Budget: brief. This month's API spend is at {status.fraction:.0%} of Nick's cap. "
                         "From now on keep every answer short, one or two sentences, and tell the family "
                         "once that you're saving your words until the month resets.")
        elif status.level == "warn" and not self._has_note(day, "Budget: warning"):
            lines.append(f"Budget: warning. This month's API spend is at {status.fraction:.0%} of Nick's cap. "
                         "If Nick is around, mention it to him once.")
        return "\n".join(lines)

    @staticmethod
    def _has_note(day: DayConversation, marker: str) -> bool:
        return any(m.get("role") == "system" and isinstance(m.get("content"), str) and marker in m["content"]
                   for m in day.messages)

    # =============================================================== a turn
    async def run_turn(self, inputs: list[Input]) -> None:
        day = self.current_day()
        now = self.clock.now()
        for item in inputs:
            if item.kind == "heard":
                self.transcripts.add(now, day.day, item.data.get("speaker") or "someone", item.data.get("text", ""))
            else:
                self.transcripts.add(now, day.day, "event", self.render_input(item))

        if self.budget.status().level == "over" and self.cfg.budget.stop_at_cap:
            log.warning("monthly cap reached; answering locally without calling the API")
            await self.speak(day, CANNED["over_budget"])
            return

        user_text = "\n".join(self.render_input(i) for i in inputs)
        if day.is_new and day.seed_text:
            user_text = (f"[earlier today — your mind restarted, so this is a text transcript of what was said "
                         f"before; any photos are gone]\n{day.seed_text}\n[end of transcript]\n\n{user_text}")
        note = self.context_note(day)
        if self.cc is not None:
            await self._run_turn_claude_code(day, user_text, note)
            return

        pending: list[dict] = []
        if self.current_effort(day) not in (None, self.cfg.claude.effort_chat):
            pending.append(effort_message(self.cfg.claude.effort_chat))
        pending.append({"role": "user", "content": user_text})
        pending.append({"role": "system", "content": note})

        await self._send_body({"t": "speak_state", "on": True})
        last_spoken = ""
        try:
            for round_no in range(MAX_ROUNDS):
                params = chat_request(self.cfg.claude, day.system_blocks(), self.tools, day.messages + pending)
                try:
                    response = await self.llm.create(**params)
                except Exception as e:   # the SDK has already retried 429/5xx/connection errors
                    log.error("Claude API call failed: %s: %s", type(e).__name__, e)
                    # Keep what was said and any tool results, so Claude sees them next
                    # turn. Drop only the context note: a system note may not be followed
                    # by the next user message, and the next turn writes a fresh one.
                    # (A failed request produced nothing, so this edits nothing the API saw.)
                    day.commit([m for m in pending
                                if not (m["role"] == "system" and isinstance(m.get("content"), str))])
                    if self.body.connected:
                        await self.body.call_tool("express", {"mood": "confused"}, 5)
                    await self.speak(day, CANNED["api_error"])
                    return

                self.budget.record(response.usage, self.cfg.claude.model, kind="chat")
                day.commit(pending + [{"role": "assistant",
                                       "content": [block_to_dict(b) for b in response.content]}])
                pending = []
                day.web_searches += sum(1 for b in response.content
                                        if b.type == "server_tool_use" and getattr(b, "name", "") == "web_search")

                if response.stop_reason == "refusal":
                    await self.speak(day, CANNED["refusal"])
                    return

                for block in response.content:
                    if block.type == "text" and block.text.strip() and block.text.strip() != QUIET_REPLY:
                        last_spoken = block.text.strip()
                        await self.speak(day, last_spoken)

                if response.stop_reason == "pause_turn":
                    continue   # a server tool (web search) paused; send the history back to continue

                if response.stop_reason == "max_tokens":
                    # Ran out of room (thinking counts towards max_tokens). Any tool
                    # call in it may be incomplete, so don't run it.
                    log.warning("reply hit max_tokens (%d)", self.cfg.claude.max_tokens)
                    if not last_spoken:
                        await self.speak(day, CANNED["cut_off"])
                    break

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if not tool_uses:
                    break

                results = [await self.run_tool(b.name, b.id, b.input) for b in tool_uses]
                if (self.current_effort(day) in (None, self.cfg.claude.effort_chat)
                        and (round_no >= 1 or any(b.name in TASK_TOOLS for b in tool_uses))):
                    # It's become a task: think a bit harder for the rest of this turn.
                    pending.append(effort_message(self.cfg.claude.effort_task))
                pending.append({"role": "user", "content": results})
            else:
                log.warning("turn stopped after %d tool rounds", MAX_ROUNDS)
                if pending:
                    # Keep the results so the history stays valid; Claude sees them next turn.
                    day.commit(pending)
        finally:
            await self._send_body({"t": "speak_state", "on": False})

        if last_spoken.endswith("?"):
            await self._send_body({"t": "listen", "seconds": self.cfg.listen_after_question_s})

    # ===================================================== claude_code brain
    async def _run_turn_claude_code(self, day: DayConversation, user_text: str, note: str) -> None:
        """One turn on the claude_code brain. The CLI runs its own tool loop; its
        tool calls come back through the MCP bridge into run_tool(), so the body
        sees exactly the same tool_calls as with the API brain."""
        cc = self.cc
        if not cc.running or cc.started_for_day != day.day:
            await cc.start(day.index_text, day.day)
        # Stream-json input only carries user messages, so the context goes at
        # the top of the user message, marked as coming from the robot's software.
        message = (f"[context from your body, written by the robot's own software]\n{note}\n"
                   f"[end of context]\n\n{user_text}")
        day.commit([{"role": "user", "content": user_text}, {"role": "system", "content": note}])
        last_spoken = ""

        async def on_text(text: str) -> None:
            nonlocal last_spoken
            if text != QUIET_REPLY:
                last_spoken = text
                await self.speak(day, text)

        await self._send_body({"t": "speak_state", "on": True})
        try:
            stats = await cc.turn(message, on_text)
        except BrainCrashed as e:
            log.error("claude_code brain failed: %s", e)
            await cc.stop_process()
            self.day = None          # next turn: fresh process + new segment seeded from the transcript
            if self.body.connected:
                await self.body.call_tool("express", {"mood": "confused"}, 5)
            await self.speak(day, CANNED["api_error"])
            return
        finally:
            await self._send_body({"t": "speak_state", "on": False})

        self.budget.record_plan(stats.usage, self.cfg.claude_code.model, stats.notional_cost_usd)
        log.info("claude_code turn: first token %.2f s, full %.2f s, %d model call(s), tokens in/out %s/%s "
                 "(cache read %s, write %s), notional US$%.4f%s",
                 stats.first_token_s or -1, stats.full_turn_s, stats.num_turns,
                 stats.usage.get("input_tokens"), stats.usage.get("output_tokens"),
                 stats.usage.get("cache_read_input_tokens"), stats.usage.get("cache_creation_input_tokens"),
                 stats.notional_cost_usd,
                 f", permission denials: {stats.permission_denials}" if stats.permission_denials else "")
        if stats.spoke:
            day.commit([{"role": "assistant", "content": [{"type": "text", "text": t} for t in stats.spoke]}])
        if last_spoken.endswith("?"):
            await self._send_body({"t": "listen", "seconds": self.cfg.listen_after_question_s})

    # ============================================================= speaking
    async def speak(self, day: DayConversation, text: str) -> None:
        self.transcripts.add(self.clock.now(), day.day, "claude", text)
        if not self.body.connected:
            log.info("(no body connected) Claude would say: %s", text)
            return
        await self.body.call_tool("say", {"text": text}, self.cfg.tool_timeouts.say)

    async def _send_body(self, msg: dict) -> None:
        if self.body.connected:
            try:
                await self.body.send(msg)
            except Exception as e:
                log.debug("couldn't send %s to body: %s", msg.get("t"), e)

    # ================================================================ tools
    async def run_tool(self, name: str, tool_use_id: str, args: dict) -> dict:
        """Run one tool call and return the tool_result block for Claude."""
        args = args if isinstance(args, dict) else {}
        try:
            if name in BODY_TOOL_NAMES:
                content, is_error = await self._body_tool(name, args)
            elif name == "memory":
                content, is_error = await asyncio.to_thread(self.memory.run, args)
            elif name == "recall":
                content, is_error = self.transcripts.recall(str(args.get("query", ""))), False
            elif name == "house":
                content, is_error = await self.house.answer(str(args.get("question", "")),
                                                            args.get("entity_ids")), False
            elif name == "timer":
                content = self.timers.add(args.get("minutes"), str(args.get("note", "")), args.get("for_person"))
                is_error = content.startswith("Error")
            else:
                content, is_error = f"Unknown tool {name!r}.", True
        except Exception as e:
            log.exception("tool %s failed", name)
            content, is_error = f"The {name} tool failed: {type(e).__name__}: {e}", True

        if name == "say" and not is_error:
            day = self.current_day()
            self.transcripts.add(self.clock.now(), day.day, "claude", str(args.get("text", "")))

        block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
        if is_error:
            block["is_error"] = True
        return block

    async def _body_tool(self, name: str, args: dict):
        if not self.body.connected:
            return "Your body isn't connected right now, so you can't do that.", True
        timeout = getattr(self.cfg.tool_timeouts, name, self.cfg.tool_timeouts.default)
        reply = await self.body.call_tool(name, args, timeout)
        if not reply.get("ok"):
            return str(reply.get("error") or "The body refused without saying why."), True

        result_text = json.dumps(reply.get("result", {}), ensure_ascii=False)
        image = reply.get("image_b64")
        if name == "look" and image:
            try:
                base64.b64decode(image, validate=True)
            except ValueError:
                return "The camera sent a broken image.", True
            return [
                {"type": "text", "text": f"Photo taken. {result_text}"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
            ], False
        return result_text, False
