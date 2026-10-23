"""Nav: getting around the house.

    Nav             the interface the agent uses
    SimNav          simulator: pretends to drive, really sends vel heartbeats
                    through the MotionGuard, so speed caps and the 10 Hz
                    heartbeat are exercised exactly as on the robot
    Ros2NavAdapter  STUB for the real robot (ROS 2 Jazzy + nav2), not written yet

Safety checks (quiet hours, keep-out, invites) happen in the agent BEFORE any
of these are called. Nav only moves.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from ..motion import MotionGuard

log = logging.getLogger(__name__)


@dataclass
class NavResult:
    ok: bool
    detail: str


class Nav:
    """`place` is the last named place the robot reached. While a drive is under
    way, `moving` is True and `origin`/`destination` say where from and to."""
    place: str | None = None
    docked: bool = False
    moving: bool = False
    origin: str | None = None
    destination: str | None = None

    def current_region(self) -> str | None:
        """Which named region the robot is in right now, or None if unknown
        (for example while driving between rooms). On the real robot this is a
        point-in-polygon test of the current map pose against the named regions
        drawn on the map; the simulator uses the last place it reached."""
        return None if self.moving else self.place

    async def go_to(self, place: str) -> NavResult:
        raise NotImplementedError

    async def approach(self, bearing_deg: float, dist_m: float, stop_at_m: float) -> NavResult:
        raise NotImplementedError

    async def dock(self) -> NavResult:
        raise NotImplementedError

    async def turn_to(self, bearing_deg: float) -> NavResult:
        raise NotImplementedError

    def cancel(self) -> None:
        raise NotImplementedError


class SimNav(Nav):
    def __init__(self, motion: MotionGuard, distances: dict[str, float], time_scale: float = 10.0,
                 approach_speed: float = 0.12, say=print, on_dock_changed=lambda docked: None):
        self.motion = motion
        self.on_dock_changed = on_dock_changed     # the sim base's charge contacts follow this
        self.distances = distances
        self.time_scale = time_scale
        self.approach_speed = approach_speed
        self.say = say
        self.place = "dock"
        self.docked = True
        self._cancel = asyncio.Event()

    @property
    def docked(self) -> bool:
        return self._docked

    @docked.setter
    def docked(self, value: bool) -> None:
        self._docked = value
        self.on_dock_changed(value)

    def cancel(self) -> None:
        self._cancel.set()

    async def _drive(self, metres: float, v: float, what: str, destination: str | None = None) -> NavResult:
        """Drive `metres` forward at up to `v`, honouring cancel and the speed caps."""
        self._cancel.clear()
        self.docked = False
        self.moving, self.origin, self.destination = True, self.place, destination or self.place
        loop = asyncio.get_running_loop()
        done = 0.0
        last = loop.time()
        await self.motion.drive(v, 0.0)
        try:
            while done < metres:
                if self._cancel.is_set():
                    return NavResult(False, f"{what} cancelled after {done:.1f} m")
                if self.motion.forward_blocked:
                    return NavResult(False, f"{what} stopped after {done:.1f} m: something is right in "
                                            "front of my face (head-height sensor)")
                await asyncio.sleep(0.05)
                now = loop.time()
                actual_v = abs(self.motion.last_sent[0])
                done += actual_v * (now - last) * self.time_scale
                last = now
            return NavResult(True, f"{what}: drove {metres:.1f} m")
        finally:
            self.moving = False
            await self.motion.halt()

    async def go_to(self, place: str) -> NavResult:
        self.say(f"  [nav] driving to the {place}...")
        result = await self._drive(self.distances.get(place, 3.0), self.motion.v_max, f"go_to {place}", place)
        if result.ok:
            self.place = place
            self.docked = place == "dock"
            self.say(f"  [nav] arrived at the {place}")
        else:
            self.place = None          # somewhere between rooms
            self.say(f"  [nav] {result.detail}")
        return result

    async def approach(self, bearing_deg: float, dist_m: float, stop_at_m: float) -> NavResult:
        await self.turn_to(bearing_deg)
        distance = max(0.0, dist_m - stop_at_m)
        self.say(f"  [nav] approaching: {distance:.1f} m to go, slowly")
        result = await self._drive(distance, self.approach_speed, "approach")   # same room: place unchanged
        self.say(f"  [nav] {result.detail}")
        return result

    async def dock(self) -> NavResult:
        if self.docked:
            return NavResult(True, "already docked")
        self.say("  [nav] heading back to the dock...")
        result = await self._drive(self.distances.get("dock", 3.0), self.motion.v_max, "dock", "dock")
        if result.ok:
            self.place, self.docked = "dock", True
            self.say("  [nav] docked, charging")
        return result

    async def turn_to(self, bearing_deg: float) -> NavResult:
        self.docked = False
        self.say(f"  [nav] turning {bearing_deg:+.0f} deg")
        w = 0.8 if bearing_deg > 0 else -0.8
        await self.motion.drive(0.0, w)
        await asyncio.sleep(min(2.0, abs(bearing_deg) / 57.3 / 0.8 / self.time_scale))
        await self.motion.halt()
        return NavResult(True, f"turned {bearing_deg:+.0f} deg")


class Ros2NavAdapter(Nav):
    """STUB — the real navigation, for phase 3 (ROS isn't installed here).

    Plan (DESIGN.md §4.1, §3.6):
      - Lidar: LDROBOT STL-19P via its ROS 2 driver (ldlidar), feeding
        slam_toolbox for the map and nav2 for localisation.
      - go_to(place): look up the place's pose in a YAML file written when the
        house is mapped (slam_toolbox), send a nav2 `NavigateToPose` action goal
        on /navigate_to_pose, wait for the result.
      - dock(): `opennav_docking` DockRobot action (AprilTag tag36h11 on the dock).
      - approach(): goal pose 1 m short of the person along their bearing,
        with nav2's speed limit server set to 0.12 m/s.
      - turn_to(): nav2 `Spin` behaviour, or direct small `cmd_vel` rotations.
      - cancel(): cancel the active action goal.
      - current_region(): point-in-polygon of the map pose against named
        regions (rooms) drawn on the map; None near a boundary or unlocalised.
      - The keep-out zones live in a nav2 keepout filter mask as well as in
        the agent's place checks.
      - IMPORTANT: nav2's `cmd_vel` must reach the wheels only through
        MotionGuard.drive(), so the speed caps and heartbeat still apply.
    """

    def __init__(self, motion: MotionGuard):
        self.motion = motion

    async def go_to(self, place: str) -> NavResult:
        raise NotImplementedError("ROS 2 nav2 adapter not written yet (phase 3)")

    async def approach(self, bearing_deg: float, dist_m: float, stop_at_m: float) -> NavResult:
        raise NotImplementedError("ROS 2 nav2 adapter not written yet (phase 3)")

    async def dock(self) -> NavResult:
        raise NotImplementedError("ROS 2 nav2 adapter not written yet (phase 3)")

    async def turn_to(self, bearing_deg: float) -> NavResult:
        raise NotImplementedError("ROS 2 nav2 adapter not written yet (phase 3)")

    def cancel(self) -> None:
        pass
