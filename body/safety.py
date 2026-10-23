"""Safety rules the BODY enforces (DESIGN.md §5), whatever the mind asks for.

The mind is a cloud model; it can be wrong or be talked into things. These
checks run on the Pi and can't be argued with:

  - quiet hours (21:00-07:00 Perth): no go_to, no approach, no body turns.
    dock() IS allowed in quiet hours — going home to the dock is exactly what
    the robot should do at night — but it obeys a "stop" like everything else.
  - keep-out places: never. Bedrooms are keep-out unless a parent has enabled
    them in body.toml, optionally only inside time windows.
  - no-look places: the camera stays shut there, and also while driving to or
    from one (the robot can't be sure which side of the door it's on).
  - "stop" / "go away" / "stop looking" are acted on here, the moment the words
    are heard, before the mind even knows
  - speed is capped lower when anyone is near (see motion.py)

(The base ESP32 has its own, lower-level reflexes too: bumper, drops, tilt,
300 ms watchdog, hard speed caps. See PROTOCOL.md §1.)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from common.clock import Clock, in_window

from .config import BodyConfig, Place

STOP_LOOKING = re.compile(r"\b(stop looking|don'?t look|no looking|close your eyes|stop watching|visor down)\b")
GO_AWAY = re.compile(r"\b(go away|leave me alone|back off|shoo|get away)\b")
STOP = re.compile(r"\b(stop|halt|freeze)\b")

# Names used in the `handled` field of `heard` (PROTOCOL.md §3).
HANDLED_NAMES = {"stop": "stop", "go_away": "go away", "stop_looking": "stop looking"}


def stop_words(text: str) -> list[str]:
    """Which local actions an utterance asks for: 'stop', 'stop_looking', 'go_away'."""
    t = text.lower()
    actions = []
    if STOP_LOOKING.search(t):
        actions.append("stop_looking")
    if GO_AWAY.search(t):
        actions.append("go_away")
    # "stop" on its own (not just as part of "stop looking"/"stop watching")
    without = STOP_LOOKING.sub(" ", t)
    if STOP.search(without):
        actions.append("stop")
    return actions


def normalise_place(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"^(the|my|your)\s+", "", n)
    return re.sub(r"\s+", " ", n)


class Safety:
    def __init__(self, cfg: BodyConfig, clock: Clock):
        self.cfg = cfg
        self.clock = clock
        self._holds: dict[str, datetime] = {}

    # ------------------------------------------------------------ time rules
    def quiet_hours(self) -> bool:
        return in_window(self.clock.now(), self.cfg.quiet_start, self.cfg.quiet_end)

    def hold(self, kind: str, seconds: float) -> None:
        """Block one kind of action ('motion', 'look', 'approach') for a while."""
        self._holds[kind] = self.clock.now() + timedelta(seconds=seconds)

    def held(self, kind: str) -> float:
        """Seconds left on a hold, or 0."""
        until = self._holds.get(kind)
        if until is None:
            return 0.0
        return max(0.0, (until - self.clock.now()).total_seconds())

    def _stopped_reason(self) -> str | None:
        if self.held("motion"):
            return f"I was just told to stop, so I'm staying put for another {self.held('motion'):.0f} seconds."
        return None

    # --------------------------------------------------------------- checks
    # Each returns None if allowed, or a short reason the robot can say.
    def place(self, name: str | None) -> Place | None:
        return self.cfg.places.get(normalise_place(name)) if name else None

    def check_go_to(self, name: str) -> str | None:
        if self.quiet_hours():
            return (f"It's quiet hours ({self.cfg.quiet_start} to {self.cfg.quiet_end}), "
                    "so I stay docked and don't drive around.")
        if reason := self._stopped_reason():
            return reason
        place = self.place(name)
        if place is None:
            known = ", ".join(n for n, p in self.cfg.places.items() if p.kind != "keep_out")
            return f"I don't know a place called {name!r}. Places I know: {known}."
        if place.kind == "keep_out":
            return f"The {normalise_place(name)} is a keep-out place for me."
        if place.windows:
            now = self.clock.now()
            if not any(in_window(now, *w.split("-")) for w in place.windows):
                return (f"I'm only allowed in the {normalise_place(name)} at "
                        f"{', '.join(place.windows)}.")
        return None

    def check_approach(self) -> str | None:
        if self.quiet_hours():
            return "It's quiet hours, so I stay docked and don't drive around."
        if reason := self._stopped_reason():
            return reason
        if self.held("approach"):
            return f"Someone asked me to go away, so I'm keeping my distance for another {self.held('approach'):.0f} s."
        return None

    def check_dock(self) -> str | None:
        """Docking is fine in quiet hours, but a "stop" still means stop."""
        return self._stopped_reason()

    def check_turn_body(self) -> str | None:
        if self.quiet_hours():
            return "quiet hours"
        if self.held("motion"):
            return "stopped"
        return None

    def check_look(self, region: str | None, origin: str | None = None,
                   destination: str | None = None) -> str | None:
        """`region` is where the robot is now (None = unknown, e.g. mid-drive)."""
        if self.held("look"):
            return f"I was asked to stop looking, so my visor stays down for another {self.held('look'):.0f} s."
        candidates = [region] if region is not None else [origin, destination]
        for name in candidates:
            place = self.place(name)
            if place is not None and place.no_look:
                where = "in" if region is not None else "on my way to or from"
                return f"I never open my visor {where} the {normalise_place(name)}."
        return None

    def speed_limit(self, people: list[dict]) -> float:
        """Top speed right now: slower if anyone is within near_person_m."""
        near = [p for p in people if isinstance(p.get("dist_m"), (int, float))
                and p["dist_m"] <= self.cfg.near_person_m]
        return self.cfg.v_near_people if near else self.cfg.v_max
