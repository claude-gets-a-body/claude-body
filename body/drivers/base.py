"""BaseLink: the base ESP32, the robot's "spinal cord" (PROTOCOL.md §1).

The base owns the wheels, the neck servos, the chest light and the safety
sensors. It stops the wheels by itself on a bump, a drop, a tilt, or 300 ms
without a `vel` command — so the Pi must keep sending `vel` while moving
(see body/motion.py).

    BaseLink        the interface: one method per command
    SerialBaseLink  the real thing, over USB serial
    SimBaseLink     a pretend base for the simulator and tests

Neck limits are applied HERE and only here (head()): pan -150..150,
tilt -15..30 (the mechanical stops are at -16 / +31).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from common.protocol import BASE_TO_PI, LIGHT_MODES, PI_TO_BASE, make

from .serial_link import JsonSerialLink, LinkDown

log = logging.getLogger(__name__)

PAN_LIMIT = 150.0
TILT_MIN, TILT_MAX = -15.0, 30.0
HEAD_SPEED_MAX = 120.0


def clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


class BaseLink:
    def __init__(self) -> None:
        self.state: dict = {}           # latest `state` message (includes measured pan/tilt)
        self.odom: dict = {}
        self.hello: dict | None = None
        self.on_event: Callable[[dict], None] = lambda msg: None

    async def _send(self, msg: dict) -> None:
        raise NotImplementedError

    @property
    def connected(self) -> bool:
        return True

    # --------------------------------------------------------- commands
    async def vel(self, v: float, w: float, seq: int) -> None:
        await self._send(make(PI_TO_BASE, "vel", v=round(v, 4), w=round(w, 4), seq=seq))

    async def head(self, pan: float, tilt: float, speed: float = 60.0) -> tuple[float, float]:
        """Move the neck. Returns the (pan, tilt) actually asked for, after clamping."""
        pan = clamp(float(pan), -PAN_LIMIT, PAN_LIMIT)
        tilt = clamp(float(tilt), TILT_MIN, TILT_MAX)
        await self._send(make(PI_TO_BASE, "head", pan=pan, tilt=tilt, speed=clamp(speed, 1, HEAD_SPEED_MAX)))
        return pan, tilt

    async def wait_head(self, pan: float, tilt: float, tolerance: float = 3.0, timeout: float = 2.0) -> bool:
        """Wait until the MEASURED pan/tilt (from `state`) are within `tolerance`
        degrees of the target. False on timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            p, t = self.state.get("pan"), self.state.get("tilt")
            if p is not None and t is not None and abs(p - pan) <= tolerance and abs(t - tilt) <= tolerance:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def light(self, mode: str, rgb: list[int] | None = None) -> None:
        if mode not in LIGHT_MODES:
            mode = "idle"
        msg = make(PI_TO_BASE, "light", mode=mode)
        if rgb:
            msg["rgb"] = [int(clamp(c, 0, 255)) for c in rgb]
        await self._send(msg)

    async def stop(self) -> None:
        await self._send(make(PI_TO_BASE, "stop"))

    async def torque(self, on: bool) -> None:
        await self._send(make(PI_TO_BASE, "torque", on=bool(on)))

    async def limits(self, v_max: float, a_max: float, w_max: float) -> None:
        await self._send(make(PI_TO_BASE, "limits", v_max=v_max, a_max=a_max, w_max=w_max))

    async def ping(self, ping_id: int) -> None:
        await self._send(make(PI_TO_BASE, "ping", id=ping_id))

    async def calibrate_floor(self) -> None:
        """Re-run drop-sensor floor calibration (motion is blocked while it runs)."""
        await self._send(make(PI_TO_BASE, "cal"))

    async def diagnostics(self) -> None:
        await self._send(make(PI_TO_BASE, "diag"))

    # --------------------------------------------------------- incoming
    def handle(self, msg: dict) -> None:
        t = msg["t"]
        if t == "state":
            self.state = msg
        elif t == "odom":
            self.odom = msg
        elif t == "hello":
            self.hello = msg
            log.info("base firmware %s, caps %s", msg.get("fw"), msg.get("caps"))
        elif t == "event":
            self.on_event(msg)


class SerialBaseLink(BaseLink):
    def __init__(self, port: str, baud: int = 921600):
        super().__init__()
        self.link = JsonSerialLink(port, baud, BASE_TO_PI, self.handle, "base")

    @property
    def connected(self) -> bool:
        return self.link.connected

    async def run(self) -> None:
        await self.link.run()

    async def _send(self, msg: dict) -> None:
        try:
            await self.link.send(msg)
        except LinkDown as e:
            log.debug("dropped %s: %s", msg["t"], e)


class SimBaseLink(BaseLink):
    """Pretend base. Remembers everything sent to it, and fakes a state.
    The neck takes `head_seconds` to reach a new position (never, if head_stuck)."""

    def __init__(self, head_seconds: float = 0.1) -> None:
        super().__init__()
        self.sent: list[dict] = []
        self.head_seconds = head_seconds
        self.head_stuck = False
        self.state = {"t": "state", "bat_v": 11.8, "bat_pct": 80, "charging": True, "on_dock": True,
                      "pack_c": 27.0, "bump": [False, False], "drop": [False, False, False],
                      "fwd_mm": [800, 800], "pan": 0.0, "tilt": 0.0, "motors": True, "fault": None}
        self.hello = {"t": "hello", "fw": "sim", "caps": {"v_max": 0.25, "a_max": 0.5, "w_max": 1.5}}
        self.verbose = False

    async def run(self) -> None:
        return None

    async def _send(self, msg: dict) -> None:
        self.sent.append(msg)
        if msg["t"] == "head" and not self.head_stuck:
            asyncio.get_running_loop().call_later(self.head_seconds, self._head_arrived, msg["pan"], msg["tilt"])
        if self.verbose and msg["t"] not in ("vel",):
            print(f"  [base] {msg}")

    def _head_arrived(self, pan: float, tilt: float) -> None:
        self.state["pan"], self.state["tilt"] = pan, tilt

    def inject_event(self, e: str, detail: str | None = None) -> None:
        msg = {"t": "event", "e": e}
        if detail:
            msg["detail"] = detail
        self.handle(msg)

    def sent_of(self, t: str) -> list[dict]:
        return [m for m in self.sent if m["t"] == t]
