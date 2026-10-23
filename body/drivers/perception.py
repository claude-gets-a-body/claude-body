"""Perception: where are people, and how far is the nearest thing in a direction?

NO FACE RECOGNITION. The camera is shuttered except for the moment of a `look`
(honest eyes, DESIGN.md §1), so it can't watch faces to recognise people. People
are therefore always anonymous here: {"name": None, "bearing": deg (+ = left),
"dist_m": m}. Where they are comes from the lidar (and the direction their voice
came from), never from the camera.

    Perception          holds the current people list; nearest_return() is the
                        lidar distance along a bearing
    SimPerception       simulator: people from `/see`, and a pretend wall
    LidarPerception     STUB: STL-19P scans -> leg/body clusters + raw ranges
"""

from __future__ import annotations

from typing import Callable


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


class Perception:
    def __init__(self) -> None:
        self.people: list[dict] = []
        self.on_change: Callable[[list[dict]], None] = lambda people: None

    def set_people(self, people: list[dict]) -> None:
        # Names are dropped: nothing on this robot can know who someone is by sight.
        anonymous = [{"name": None, "bearing": float(p.get("bearing", 0.0)), "dist_m": float(p.get("dist_m", 0.0))}
                     for p in people]
        if anonymous != self.people:
            self.people = anonymous
            self.on_change(anonymous)

    def nearest_person(self) -> dict | None:
        return min(self.people, key=lambda p: p["dist_m"]) if self.people else None

    def nearest_return(self, bearing_deg: float, width_deg: float = 15.0) -> float | None:
        """Distance (m) of the nearest lidar return within +-width of a bearing,
        or None if there's nothing there."""
        hits = [p["dist_m"] for p in self.people if _angle_gap(p["bearing"], bearing_deg) <= width_deg]
        return min(hits) if hits else None


class SimPerception(Perception):
    """People come from the sim's `/see`; anything else is a wall `wall_m` away."""

    def __init__(self, wall_m: float = 3.0) -> None:
        super().__init__()
        self.wall_m = wall_m

    def nearest_return(self, bearing_deg: float, width_deg: float = 15.0) -> float | None:
        person = super().nearest_return(bearing_deg, width_deg)
        return person if person is not None else self.wall_m


class LidarPerception(Perception):
    """STUB (phase 3, needs the base and the STL-19P lidar on ROS 2).
      - nearest_return(): minimum of the /scan ranges within the bearing window,
        ignoring the three masked pillar shadows.
      - people: leg/body clusters from the scan, with distance and bearing,
        always anonymous. Used for the 0.12 m/s near-people speed limit.
    """

    def nearest_return(self, bearing_deg: float, width_deg: float = 15.0) -> float | None:
        raise NotImplementedError("lidar perception not written yet (phase 3)")
