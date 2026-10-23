"""FaceLink: the head ESP32 (PROTOCOL.md §2) — eyes, ears, visor, touch pad.

It also reports `range` at 10 Hz: a forward ToF at head height (head_mm;
-1 = no reading, 4000 = clear) that catches table edges and benchtops the lidar
can't see. Until the first reading arrives, head_mm is -1, which counts as "slow".

The visor is the robot's honesty: the face board reports `open` only when the
visor-up switch is actually closed. `visor_state` here is always the last
state the board reported, and the camera refuses to capture unless it is "open".
On boot the face closes the visor, so we start from "closed".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from common.protocol import FACE_TO_PI, MOODS, PI_TO_FACE, make

from .serial_link import JsonSerialLink, LinkDown

log = logging.getLogger(__name__)


class FaceLink:
    def __init__(self) -> None:
        self.visor_state = "closed"
        self.head_mm: int = -1
        self.hello: dict | None = None
        self.on_touch: Callable[[str], None] = lambda gesture: None
        self.on_range: Callable[[int], None] = lambda head_mm: None
        self._visor_changed = asyncio.Event()

    async def _send(self, msg: dict) -> None:
        raise NotImplementedError

    @property
    def connected(self) -> bool:
        return True

    # --------------------------------------------------------- commands
    async def mood(self, m: str, ms: int | None = None) -> None:
        msg = make(PI_TO_FACE, "mood", m=m if m in MOODS else "neutral")
        if ms is not None:
            msg["ms"] = int(ms)
        await self._send(msg)

    async def gaze(self, x: float, y: float) -> None:
        await self._send(make(PI_TO_FACE, "gaze", x=max(-1.0, min(1.0, x)), y=max(-1.0, min(1.0, y))))

    async def blink(self) -> None:
        await self._send(make(PI_TO_FACE, "blink"))

    async def ears(self, left: float | None = None, right: float | None = None, wiggle: bool = False) -> None:
        msg = make(PI_TO_FACE, "ears")
        if wiggle:
            msg["wiggle"] = True
        else:
            msg["l"] = max(0.0, min(1.0, left if left is not None else 0.5))
            msg["r"] = max(0.0, min(1.0, right if right is not None else 0.5))
        await self._send(msg)

    async def visor(self, open_: bool) -> None:
        await self._send(make(PI_TO_FACE, "visor", open=bool(open_)))

    async def bright(self, b: float) -> None:
        await self._send(make(PI_TO_FACE, "bright", b=max(0.0, min(1.0, b))))

    async def wait_visor(self, wanted: str, timeout: float) -> bool:
        """Wait until the board reports `wanted` ('open'/'closed'). False on timeout or jam."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while self.visor_state != wanted:
            if self.visor_state == "jammed":
                return False
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            self._visor_changed.clear()
            try:
                await asyncio.wait_for(self._visor_changed.wait(), remaining)
            except asyncio.TimeoutError:
                return False
        return True

    # --------------------------------------------------------- incoming
    def handle(self, msg: dict) -> None:
        t = msg["t"]
        if t == "visor":
            self.visor_state = msg["state"]
            self._visor_changed.set()
        elif t == "touch":
            self.on_touch(msg["g"])
        elif t == "range":
            try:
                self.head_mm = int(msg["head_mm"])
            except (TypeError, ValueError):
                self.head_mm = -1
            self.on_range(self.head_mm)
        elif t == "hello":
            self.hello = msg
            self.visor_state = "closed"   # the face closes the visor on boot
            self._visor_changed.set()


class SerialFaceLink(FaceLink):
    def __init__(self, port: str, baud: int = 921600):
        super().__init__()
        self.link = JsonSerialLink(port, baud, FACE_TO_PI, self.handle, "face")

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
            if msg["t"] == "visor":
                # Can't reach the face: we can't know the visor's real state, so
                # treat it as not open. (The camera only reads after "open".)
                self.visor_state = "closed"


class SimFaceLink(FaceLink):
    """Pretend face. The visor takes a moment to move, like the real servo."""

    def __init__(self, visor_seconds: float = 0.15, jam: bool = False):
        super().__init__()
        self.sent: list[dict] = []
        self.visor_seconds = visor_seconds
        self.jam = jam
        self.verbose = False
        self.hello = {"t": "hello", "fw": "sim"}
        self.head_mm = 4000          # the sim starts with a clear view ahead

    async def run(self) -> None:
        return None

    async def _send(self, msg: dict) -> None:
        self.sent.append(msg)
        if self.verbose:
            if msg["t"] == "mood":
                print(f"  [face] eyes: {msg['m']}")
            elif msg["t"] == "visor":
                print(f"  [face] visor {'UP (camera can see)' if msg['open'] else 'DOWN (camera covered)'}")
        if msg["t"] == "visor":
            self.handle({"t": "visor", "state": "moving"})
            asyncio.get_running_loop().call_later(self.visor_seconds, self._visor_arrived, msg["open"])

    def _visor_arrived(self, open_: bool) -> None:
        if self.jam:
            self.handle({"t": "visor", "state": "jammed"})
        else:
            self.handle({"t": "visor", "state": "open" if open_ else "closed"})

    def touch(self, gesture: str) -> None:
        self.handle({"t": "touch", "g": gesture})

    def set_head_range(self, head_mm: int) -> None:
        """Simulator: pretend the head ToF reads this (the real face sends it at 10 Hz)."""
        self.handle({"t": "range", "head_mm": head_mm})
