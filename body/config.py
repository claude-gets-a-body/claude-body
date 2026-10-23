"""Body agent settings (runs on the robot's Pi 5).

Defaults are here; config/body.example.toml shows how to override them.
The BODY_TOKEN secret comes from the environment, never the file.

Place kinds:
  normal    the robot may drive there (outside quiet hours), optionally only
            within `windows`, e.g. ["15:30-19:00"] (Perth time)
  keep_out  never

Bedrooms are keep_out by default. The robot has no face recognition (its
camera is shuttered except during `look`), so it can't tell who is inviting it.
Instead a parent enables a bedroom in body.toml:

    [places."child 1 bedroom"]
    kind = "normal"
    windows = ["15:30-19:00"]
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Place:
    kind: str = "normal"                   # normal / keep_out
    windows: list[str] = field(default_factory=list)   # "HH:MM-HH:MM"; empty = any time
    no_look: bool = False                  # the camera never opens here
    sim_distance_m: float = 3.0            # simulator only: how far it is


def default_places() -> dict[str, Place]:
    # Placeholder layout. Rename to match the house once it's mapped (DESIGN.md phase 3).
    return {
        "dock": Place(),
        "lounge": Place(),
        "kitchen": Place(),
        "dining room": Place(),
        "hallway": Place(),
        "study": Place(),
        "front door": Place(),
        "bathroom": Place(kind="keep_out", no_look=True),
        "ensuite": Place(kind="keep_out", no_look=True),
        "toilet": Place(kind="keep_out", no_look=True),
        "laundry": Place(kind="keep_out"),
        "outside": Place(kind="keep_out"),
        "backyard": Place(kind="keep_out"),
        "garage": Place(kind="keep_out"),
        "main bedroom": Place(kind="keep_out", no_look=True),
        "child 1 bedroom": Place(kind="keep_out", no_look=True),
        "child 2 bedroom": Place(kind="keep_out", no_look=True),
    }


@dataclass
class BodyConfig:
    body_id: str = "claude-body-1"
    mind_url: str = "ws://k8:8765/body"
    body_token: str = ""

    # drivers: which implementation to use for each part
    base_driver: str = "serial"            # serial / sim / none
    face_driver: str = "serial"            # serial / sim
    camera_driver: str = "opencv"          # opencv / folder
    nav_driver: str = "sim"                # sim / ros2 (stub)
    voice_driver: str = "console"          # console / local (stub)

    base_port: str = "/dev/serial/by-id/claude-base"   # set to the real by-id path
    face_port: str = "/dev/serial/by-id/claude-face"
    baud: int = 921600
    camera_index: int = 0
    camera_max_px: int = 1024
    jpeg_quality: int = 80
    sim_frames_dir: str = str(PROJECT_DIR / "sim_frames")
    sim_time_scale: float = 10.0           # simulator drives 10x faster than life

    # safety (enforced here in the body, not in the mind)
    quiet_start: str = "21:00"
    quiet_end: str = "07:00"
    v_max: float = 0.25                    # m/s, matches the base firmware cap
    w_max: float = 1.5                     # rad/s
    a_max: float = 0.5                     # m/s^2
    v_near_people: float = 0.12            # m/s within near_person_m of anyone
    near_person_m: float = 1.0
    approach_stop_m: float = 1.0
    heartbeat_hz: float = 10.0             # vel resend rate while moving (base needs >= 5 Hz)
    head_only_turn_deg: float = 60.0       # turn just the head up to this angle
    drive_head_pan_max: float = 20.0       # head kept facing forward (+-20 deg) while driving
    speaker_fresh_s: float = 30.0          # approach() needs someone to have spoken this recently
    event_cooldown_s: float = 60.0         # each base event type goes to the mind at most this often
    stop_hold_s: float = 10.0              # after "stop": no driving for this long
    stop_looking_hold_s: float = 120.0     # after "stop looking": no photos for this long
    go_away_hold_s: float = 300.0          # after "go away": no approaching for this long
    places: dict[str, Place] = field(default_factory=default_places)

    state_every_s: float = 30.0
    visor_open_timeout_s: float = 2.0


def _apply(obj, data: dict) -> None:
    known = {f.name for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            raise ValueError(f"unknown setting {key!r}")
        if key == "places":
            setattr(obj, key, {name.lower(): Place(**p) for name, p in value.items()})
        elif is_dataclass(getattr(obj, key)) and isinstance(value, dict):
            _apply(getattr(obj, key), value)
        else:
            setattr(obj, key, value)


def load(path: str | None = None) -> BodyConfig:
    cfg = BodyConfig()
    if path:
        with open(path, "rb") as f:
            _apply(cfg, tomllib.load(f))
    cfg.body_token = os.environ.get("BODY_TOKEN", cfg.body_token)
    return cfg
