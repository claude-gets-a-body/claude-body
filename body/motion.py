"""MotionGuard: the only way anything on the Pi drives the wheels.

Three jobs:

1. Heartbeat. The base ESP32 stops the wheels if it hears no `vel` for 300 ms
   (PROTOCOL.md §1). While a drive command is active, the guard re-sends `vel`
   at 10 Hz. When the command ends, it sends one zero `vel` and goes quiet, so
   if the Pi or this program dies, the base's watchdog stops the robot.

2. Speed caps, applied to every `vel` at send time (so a new cap takes effect
   within one heartbeat, even mid-drive):
     - 0.25 m/s normally, 0.12 m/s with someone within 1 m (set_people_limit)
     - the head-height range sensor (set_head_range), forward motion only:
         clear  (>= 300 mm)            normal
         slow   (< 300 mm, or -1 = no reading)   forward capped at 0.05 m/s
         block  (< 150 mm)             stop now; no forward motion at all
       Reverse and turning on the spot are still allowed when blocked.

3. Telling the base. This class is the one place that sends `limits` (and the
   `stop` when the head range blocks), so the firmware's caps match ours.
   The base firmware clamps again on its side; this is the Pi's half.

Nav implementations call drive() and halt(); nothing else sends `vel`.
"""

from __future__ import annotations

import asyncio
import logging

from .drivers.base import BaseLink

log = logging.getLogger(__name__)

HEAD_SLOW_MM = 300
HEAD_STOP_MM = 150
HEAD_SLOW_V = 0.05


def head_zone(head_mm: int | None) -> str:
    if head_mm is None or head_mm < 0:
        return "slow"            # no reading: be careful
    if head_mm < HEAD_STOP_MM:
        return "block"
    if head_mm < HEAD_SLOW_MM:
        return "slow"
    return "clear"


class MotionGuard:
    def __init__(self, base: BaseLink, v_max: float, w_max: float, a_max: float = 0.5, hz: float = 10.0):
        self.base = base
        self.v_max = v_max
        self.w_max = w_max
        self.a_max = a_max
        self.period = 1.0 / hz
        self.speed_limit = v_max          # people limit, set by the agent
        self.head_zone = "slow"           # until the face sends its first range reading
        self._target = (0.0, 0.0)
        self._seq = 0
        self._task: asyncio.Task | None = None
        self._limits_sent: float | None = None
        self.last_sent = (0.0, 0.0)

    # ------------------------------------------------------------- state
    @property
    def moving(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def moving_forward(self) -> bool:
        return self.moving and self._target[0] > 0

    @property
    def forward_blocked(self) -> bool:
        return self.head_zone == "block"

    def forward_cap(self) -> float:
        cap = min(self.speed_limit, self.v_max)
        if self.head_zone == "slow":
            cap = min(cap, HEAD_SLOW_V)
        elif self.head_zone == "block":
            cap = 0.0
        return cap

    def clamp(self, v: float, w: float) -> tuple[float, float]:
        if v > 0:
            v = min(v, self.forward_cap())
        else:
            v = max(v, -min(self.speed_limit, self.v_max))
        w = max(-self.w_max, min(self.w_max, w))
        return v, w

    # ------------------------------------------------------------ inputs
    async def set_people_limit(self, limit: float) -> None:
        if limit != self.speed_limit:
            self.speed_limit = limit
            await self._sync_limits()

    async def set_head_range(self, head_mm: int | None) -> None:
        zone = head_zone(head_mm)
        if zone == self.head_zone:
            return
        self.head_zone = zone
        if zone == "block" and self.moving_forward:
            log.warning("something at head height %s mm ahead: stopping", head_mm)
            await self.base.stop()
            await self._send(*self._target)        # clamped to v = 0 now
        await self._sync_limits()

    async def _sync_limits(self) -> None:
        """Send `limits` to the base when the cap it should enforce changes."""
        wanted = min(self.speed_limit, self.v_max)
        if self.moving_forward and self.head_zone == "slow":
            wanted = min(wanted, HEAD_SLOW_V)
        if wanted != self._limits_sent:
            self._limits_sent = wanted
            await self.base.limits(v_max=wanted, a_max=self.a_max, w_max=self.w_max)

    # ------------------------------------------------------------ driving
    async def drive(self, v: float, w: float) -> None:
        """Set the wanted speed. Keeps being sent at 10 Hz until halt()."""
        self._target = (v, w)
        if v == 0 and w == 0:
            await self.halt()
            return
        if not self.moving:
            self._task = asyncio.create_task(self._heartbeat())
        await self._sync_limits()

    async def halt(self) -> None:
        self._target = (0.0, 0.0)
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._send(0.0, 0.0)
        await self._sync_limits()

    async def _send(self, v: float, w: float) -> None:
        self._seq += 1
        v, w = self.clamp(v, w)
        self.last_sent = (v, w)
        await self.base.vel(v, w, self._seq)

    async def _heartbeat(self) -> None:
        while True:
            await self._send(*self._target)
            await asyncio.sleep(self.period)
