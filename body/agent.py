"""The body agent: runs on the Pi, connects to the mind, and drives the hardware.

What it does:
  - keeps a WebSocket open to the mind (PROTOCOL.md §3), reconnecting forever,
    with "Authorization: Bearer <BODY_TOKEN>"
  - passes up what the robot hears (`heard`), senses (`saw`, anonymous, from
    lidar), feels (`touch`), its condition (`state`, every 30 s and on change)
    and base reflex `event`s (each type at most once a minute)
  - carries out `tool_call`s from the mind and answers each with `tool_result`
  - enforces the safety rules itself (body/safety.py, body/motion.py) — a
    refusal comes back to the mind as ok: false with a reason Claude can repeat
  - acts on "stop", "go away" and "stop looking" the moment they're heard,
    before the mind is even told

Honest eyes: the camera is used only inside `look`. Nothing here recognises
faces, so `speaker` is whatever the voice pipeline says (None on the robot for
now) and people are anonymous.

If the mind goes away (Wi-Fi drop, K8 restart) the robot stops whatever it was
doing and looks confused until the connection comes back.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import logging

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from common.protocol import BODY_TO_MIND, BODY_TOOLS, MIND_TO_BODY, MOODS, decode, encode, make

from .config import BodyConfig
from .drivers.base import BaseLink
from .drivers.camera import Camera, VisorClosed
from .drivers.face import FaceLink
from .drivers.nav import Nav
from .drivers.perception import Perception
from .drivers.voice import Utterance, Voice
from .motion import MotionGuard
from .safety import HANDLED_NAMES, Safety, normalise_place, stop_words

log = logging.getLogger(__name__)

LOOK_DIRECTIONS = {            # name -> (pan, tilt) degrees; tilt range is -15..30
    "ahead": (0, 10), "forward": (0, 10), "left": (60, 10), "right": (-60, 10),
    "up": (0, 28), "down": (0, -12),
}
MOOD_LIGHT = {"thinking": "think", "listening": "listen", "sleepy": "sleep", "asleep": "sleep"}
FORWARDED_EVENTS = {"bump_l": "bump", "bump_r": "bump",
                    "drop_l": "drop", "drop_r": "drop", "drop_rear": "drop",
                    "tilt": "tilt", "low_battery": "low_battery", "pack_hot": "pack_hot",
                    "servo_error": "servo_error", "watchdog": "watchdog"}
HEAD_TOLERANCE_DEG = 3.0
HEAD_SETTLE_TIMEOUT_S = 2.0


def wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


class BodyAgent:
    def __init__(self, cfg: BodyConfig, base: BaseLink, face: FaceLink, camera: Camera, nav: Nav,
                 voice: Voice, perception: Perception, motion: MotionGuard, safety: Safety):
        self.cfg = cfg
        self.base = base
        self.face = face
        self.camera = camera
        self.nav = nav
        self.voice = voice
        self.perception = perception
        self.motion = motion
        self.safety = safety
        self.ws = None
        self.last_speaker: str | None = None
        self.last_bearing: float = 0.0
        self.last_heard_at = None                 # clock time of the last utterance
        self._ids = itertools.count(1)
        self._last_state_sent: dict | None = None
        self._last_saw_sent = 0.0
        self._event_sent_at: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self.connected = asyncio.Event()

        base.on_event = self._on_base_event
        face.on_touch = self._on_touch
        face.on_range = self._on_head_range
        perception.on_change = self._on_people_changed

    # ============================================================ connection
    async def run(self) -> None:
        """Connect to the mind and keep the connection up forever."""
        await self.motion.set_head_range(self.face.head_mm)
        workers = [asyncio.create_task(self._listen_loop(), name="listen"),
                   asyncio.create_task(self._state_loop(), name="state")]
        delay = 1.0
        try:
            while True:
                try:
                    async with connect(self.cfg.mind_url, max_size=8 * 1024 * 1024,
                                       additional_headers={"Authorization": f"Bearer {self.cfg.body_token}"}) as ws:
                        delay = 1.0
                        await self._session(ws)
                except InvalidStatus as e:
                    log.error("the mind refused the connection (HTTP %s) — check BODY_TOKEN",
                              e.response.status_code)
                except (OSError, ConnectionClosed, asyncio.TimeoutError) as e:
                    log.warning("mind connection: %s", e or type(e).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15.0)
        finally:
            for w in workers:
                w.cancel()

    async def _session(self, ws) -> None:
        self.ws = ws
        self.connected.set()
        log.info("connected to the mind at %s", self.cfg.mind_url)
        try:
            await self._send("hello", body_id=self.cfg.body_id,
                             fw={"base": (self.base.hello or {}).get("fw"), "face": (self.face.hello or {}).get("fw")},
                             caps=BODY_TOOLS)
            self._last_state_sent = None
            await self._maybe_send_state(force=True)
            async for raw in ws:
                msg = decode(raw, MIND_TO_BODY)
                if msg is None:
                    continue
                if msg["t"] == "tool_call":
                    self._spawn(self._run_tool_call(msg))
                elif msg["t"] == "listen":
                    self.voice.open_followup(float(msg["seconds"]))
                    await self.face.mood("listening")
                elif msg["t"] == "speak_state":
                    await self.face.mood("thinking" if msg["on"] else "neutral")
                    await self.base.light("think" if msg["on"] else "idle")
        finally:
            self.ws = None
            self.connected.clear()
            # Lost the mind: stop politely, look confused.
            self.nav.cancel()
            await self.motion.halt()
            await self.face.visor(False)
            await self.face.mood("confused")

    async def _send(self, t: str, **fields) -> None:
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(encode(make(BODY_TO_MIND, t, **fields)))
        except ConnectionClosed:
            pass

    # ================================================================ inputs
    async def _listen_loop(self) -> None:
        while True:
            utt = await self.voice.next_utterance()
            await self.on_utterance(utt)

    async def on_utterance(self, utt: Utterance) -> None:
        handled = await self.obey_stop_words(utt.text)
        # The mic array is on the head: its angle is relative to where the head
        # points, so add the neck pan to get a bearing relative to the body.
        pan = float(self.base.state.get("pan") or 0.0)
        bearing = wrap180(utt.doa + pan)
        self.last_speaker = utt.speaker
        self.last_bearing = bearing
        self.last_heard_at = self.safety.clock.now()
        msg = make(BODY_TO_MIND, "heard", text=utt.text, speaker=utt.speaker, doa=round(bearing, 1),
                   conf=utt.conf, id=f"u{next(self._ids)}")
        if handled:
            msg["handled"] = ", ".join(handled)    # the stop words already obeyed
        if self.ws is not None:
            try:
                await self.ws.send(encode(msg))
            except ConnectionClosed:
                pass

    async def obey_stop_words(self, text: str) -> list[str]:
        """Act on stop / go away / stop looking right now. Returns which ones."""
        actions = stop_words(text)
        if "stop" in actions:
            await self.full_stop()
            self.safety.hold("motion", self.cfg.stop_hold_s)
        if "stop_looking" in actions:
            await self.face.visor(False)
            self.safety.hold("look", self.cfg.stop_looking_hold_s)
        if "go_away" in actions:
            self.nav.cancel()
            await self.motion.halt()
            self.safety.hold("approach", self.cfg.go_away_hold_s)
        return [HANDLED_NAMES[a] for a in actions]

    async def full_stop(self) -> None:
        self.nav.cancel()
        await self.motion.halt()
        await self.base.stop()

    def _on_touch(self, gesture: str) -> None:
        self._spawn(self._send("touch", g=gesture))

    def _on_base_event(self, msg: dict) -> None:
        name = FORWARDED_EVENTS.get(msg.get("e"))
        if name in ("bump", "drop", "tilt"):
            self.nav.cancel()       # the base has already stopped the wheels itself
        if not name:
            return
        # Each event type goes to the mind at most once per event_cooldown_s:
        # a robot wedged against a chair would otherwise send a bump 5 times a second.
        now = asyncio.get_running_loop().time()
        last = self._event_sent_at.get(name)
        if last is not None and now - last < self.cfg.event_cooldown_s:
            return
        self._event_sent_at[name] = now
        self._spawn(self._send("event", e=name, detail=msg.get("detail") or msg.get("e")))

    def _on_head_range(self, head_mm: int) -> None:
        self._spawn(self.motion.set_head_range(head_mm))

    def _on_people_changed(self, people: list[dict]) -> None:
        self._spawn(self.motion.set_people_limit(self.safety.speed_limit(people)))
        self._spawn(self._send_saw())

    async def _send_saw(self) -> None:
        loop = asyncio.get_running_loop()
        wait = 1.0 - (loop.time() - self._last_saw_sent)    # at most once a second
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_saw_sent = loop.time()
        await self._send("saw", people=self.perception.people, ts=round(loop.time(), 2))

    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ================================================================ state
    def current_state(self) -> dict:
        s = self.base.state
        return {"battery_pct": s.get("bat_pct"), "charging": bool(s.get("charging")),
                "docked": bool(s.get("on_dock")) or self.nav.docked, "place": self.nav.current_region(),
                "fault": s.get("fault"), "quiet_hours": self.safety.quiet_hours()}

    async def _maybe_send_state(self, force: bool = False) -> None:
        state = self.current_state()
        if force or state != self._last_state_sent:
            self._last_state_sent = state
            await self._send("state", **state)

    async def _state_loop(self) -> None:
        elapsed = 0.0
        while True:
            await asyncio.sleep(1.0)
            elapsed += 1.0
            force = elapsed >= self.cfg.state_every_s
            if force:
                elapsed = 0.0
            await self._maybe_send_state(force=force)

    # ================================================================= head
    async def point_head(self, pan: float, tilt: float) -> tuple[float, float]:
        """Every head move goes through here. While driving, the head stays
        facing forward (pan within +-drive_head_pan_max) so the head-height
        range sensor is looking where the robot is going."""
        if self.motion.moving or self.nav.moving:
            limit = self.cfg.drive_head_pan_max
            pan = max(-limit, min(limit, pan))
        return await self.base.head(pan, tilt)

    async def _face_forward_for_driving(self) -> None:
        await self.point_head(0, 0)

    # ================================================================= tools
    async def _run_tool_call(self, msg: dict) -> None:
        reply = await self.execute(msg["name"], msg.get("args") or {})
        await self._send("tool_result", call_id=msg["call_id"], **reply)

    async def execute(self, name: str, args: dict) -> dict:
        """Run one tool. Returns the tool_result fields: ok + result/error (+ image_b64)."""
        handler = getattr(self, f"tool_{name}", None)
        if name not in BODY_TOOLS or handler is None:
            return {"ok": False, "error": f"The body doesn't know a tool called {name!r}."}
        try:
            return await handler(**args)
        except TypeError as e:
            return {"ok": False, "error": f"Bad arguments for {name}: {e}"}
        except NotImplementedError as e:
            return {"ok": False, "error": f"{name} isn't available on this body yet: {e}"}
        except Exception as e:
            log.exception("tool %s failed", name)
            return {"ok": False, "error": f"{name} failed: {type(e).__name__}: {e}"}

    @staticmethod
    def refuse(reason: str) -> dict:
        return {"ok": False, "error": reason}

    def _forward_blocked_reason(self) -> str | None:
        if self.motion.forward_blocked:
            return "Something is right in front of my face (my head-height sensor), so I can't drive forward."
        return None

    async def tool_say(self, text: str, voice_style: str = "normal") -> dict:
        await self.base.light("speak")
        finished = await self.voice.speak(text, "quiet" if self.safety.quiet_hours() else voice_style)
        await self.base.light("idle")
        if not finished:
            return self.refuse("Interrupted: someone started talking.")
        return {"ok": True, "result": {"spoken": True}}

    async def tool_express(self, mood: str) -> dict:
        if mood not in MOODS:
            return self.refuse(f"Unknown mood {mood!r}.")
        await self.face.mood(mood)
        await self.base.light(MOOD_LIGHT.get(mood, "idle"))
        if mood == "happy":
            await self.face.ears(wiggle=True)
        return {"ok": True, "result": {"mood": mood}}

    def _bearing_of(self, target: str | None) -> tuple[float | None, str]:
        """'speaker' / 'nearest' / '30' -> a bearing in degrees (+ left).
        People can't be found by name: there's no face recognition."""
        if target is None or target == "":
            return None, "where I'm facing"
        t = str(target).strip().lower()
        if t in ("speaker", "whoever spoke", "voice", "me", "you"):
            return self.last_bearing, "the last speaker"
        if t in ("someone", "nearest", "anyone", "nearest person"):
            person = self.perception.nearest_person()
            if person is not None:
                return person["bearing"], "the nearest person"
            return None, ""
        try:
            return float(t), f"{float(t):+.0f} degrees"
        except ValueError:
            return None, ""

    async def tool_look(self, at: str | None = None) -> dict:
        reason = self.safety.check_look(self.nav.current_region(), self.nav.origin if self.nav.moving else None,
                                        self.nav.destination if self.nav.moving else None)
        if reason:
            return self.refuse(reason)
        if at and str(at).lower() in LOOK_DIRECTIONS:
            pan, tilt = LOOK_DIRECTIONS[str(at).lower()]
            where = str(at).lower()
        else:
            bearing, where = self._bearing_of(at)
            if at and bearing is None:
                return self.refuse(f"I can't point my head at {at!r}. I can look ahead, left, right, up, down, "
                                   "at an angle, at whoever spoke, or at the nearest person.")
            pan = bearing if bearing is not None else float(self.base.state.get("pan") or 0.0)
            tilt = 20 if bearing is not None else float(self.base.state.get("tilt") or 10.0)

        pan, tilt = await self.point_head(pan, tilt)
        # Wait for the head to actually get there before the visor opens, so the
        # photo is of what was asked for (and the visor isn't up while turning).
        if not await self.base.wait_head(pan, tilt, HEAD_TOLERANCE_DEG, HEAD_SETTLE_TIMEOUT_S):
            return self.refuse("My head didn't reach the position to look, so I didn't open my visor.")

        await self.face.visor(True)
        if not await self.face.wait_visor("open", self.cfg.visor_open_timeout_s):
            await self.face.visor(False)
            return self.refuse(f"My visor didn't open (it reports {self.face.visor_state!r}).")
        try:
            jpeg = await asyncio.to_thread(self.camera.capture_jpeg, self.nav.current_region())
        except VisorClosed as e:
            return self.refuse(str(e))
        finally:
            await self.face.visor(False)     # always back down, photo or not
        return {"ok": True, "result": {"looked_at": where, "pan": round(pan), "tilt": round(tilt),
                                       "jpeg_bytes": len(jpeg)},
                "image_b64": base64.b64encode(jpeg).decode("ascii")}

    async def tool_turn_to(self, target: str) -> dict:
        bearing, what = self._bearing_of(target)
        if bearing is None:
            return self.refuse(f"I don't know where {target!r} is. I can turn to whoever spoke last, "
                               "the nearest person, or an angle.")
        bearing = wrap180(bearing)
        body_turn_blocked = self.safety.check_turn_body()
        if (abs(bearing) <= self.cfg.head_only_turn_deg or body_turn_blocked or self.nav.docked
                or self.nav.moving):        # never spin the body in the middle of a drive
            await self.point_head(bearing, 15)
            how = "head"
        else:
            await self.nav.turn_to(bearing)
            await self.point_head(0, 15)
            how = "body"
            self.last_bearing = 0.0
        return {"ok": True, "result": {"facing": what, "bearing": round(bearing), "turned": how}}

    async def tool_go_to(self, place: str) -> dict:
        reason = self.safety.check_go_to(place) or self._forward_blocked_reason()
        if reason:
            return self.refuse(reason)
        name = normalise_place(place)
        await self._face_forward_for_driving()
        result = await self.nav.go_to(name)
        await self._maybe_send_state()
        if not result.ok:
            return self.refuse(result.detail)
        return {"ok": True, "result": {"place": self.nav.place, "detail": result.detail}}

    async def tool_approach(self, person: str | None = None) -> dict:
        """Drive towards whoever spoke last: the bearing from their voice (the
        XVF3800's direction of arrival) and the distance from the nearest lidar
        return on that bearing. Stops approach_stop_m short. `person` is only a
        label: the robot can't pick people out by name."""
        reason = self.safety.check_approach() or self._forward_blocked_reason()
        if reason:
            return self.refuse(reason)
        if self.last_heard_at is None or \
                (self.safety.clock.now() - self.last_heard_at).total_seconds() > self.cfg.speaker_fresh_s:
            return self.refuse("I find people by their voice. Ask them to say something so I can hear where they are.")
        bearing = self.last_bearing
        dist = self.perception.nearest_return(bearing)
        if dist is None:
            return self.refuse("I can hear where you are but can't find you with my lidar.")
        if dist <= self.cfg.approach_stop_m:
            return {"ok": True, "result": {"detail": "already close enough", "dist_m": round(dist, 2)}}
        await self._face_forward_for_driving()
        result = await self.nav.approach(bearing, dist, self.cfg.approach_stop_m)
        await self._maybe_send_state()
        if not result.ok:
            return self.refuse(result.detail)
        return {"ok": True, "result": {"detail": result.detail, "bearing": round(bearing),
                                       "stopped_at_m": self.cfg.approach_stop_m}}

    async def tool_dock(self) -> dict:
        reason = self.safety.check_dock()      # allowed in quiet hours, not after "stop"
        if reason:
            return self.refuse(reason)
        await self._face_forward_for_driving()
        result = await self.nav.dock()
        await self._maybe_send_state()
        if not result.ok:
            return self.refuse(result.detail)
        return {"ok": True, "result": {"detail": result.detail}}

    async def tool_sleep(self) -> dict:
        await self.face.visor(False)
        await self.point_head(0, -12)
        await self.face.mood("asleep")
        await self.base.light("sleep")
        return {"ok": True, "result": {"asleep": True}}

    async def tool_wake(self) -> dict:
        await self.face.mood("neutral")
        await self.base.light("idle")
        return {"ok": True, "result": {"awake": True}}

    async def tool_stop(self) -> dict:
        await self.full_stop()
        return {"ok": True, "result": {"stopped": True}}

    async def close(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        with contextlib.suppress(Exception):
            await self.motion.halt()
