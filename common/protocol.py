"""Wire protocol helpers (see docs/PROTOCOL.md).

All three links use the same framing: one JSON object per message, UTF-8, with a
"t" field naming the message type.

- Serial links (Pi <-> base ESP32, Pi <-> face ESP32): one object per line ("\n").
- WebSocket link (body <-> mind): one object per WebSocket text frame.

The rule from PROTOCOL.md that matters most here: unknown message types are
ignored, never fatal. `decode()` therefore returns None for anything it cannot
use instead of raising, and the callers simply skip None.

The tables below list the REQUIRED fields of each message type. Optional fields
(for example `rgb` on `light`, or `image_b64` on `tool_result`) are allowed but
not listed. `make()` refuses to build a message with a required field missing,
so a typo shows up as an error on our side instead of a silent no-op on an ESP32.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PROTOCOL.md §1 — Pi <-> base ESP32 ("spine"), USB CDC serial, 921600 baud
# ---------------------------------------------------------------------------
PI_TO_BASE = {
    "vel": ["v", "w", "seq"],
    "head": ["pan", "tilt", "speed"],
    "light": ["mode"],
    "stop": [],
    "torque": ["on"],
    "limits": ["v_max", "a_max", "w_max"],
    "ping": ["id"],
    "cal": [],           # re-run drop-sensor floor calibration
    "diag": [],          # ask for firmware diagnostics
}
BASE_TO_PI = {
    "odom": ["x", "y", "th", "v", "w", "ts"],
    "imu": ["roll", "pitch", "yaw", "gz"],
    "state": ["bat_v", "bat_pct", "charging", "on_dock", "pack_c", "bump", "drop",
              "fwd_mm", "pan", "tilt", "motors", "fault"],
    "event": ["e"],
    "pong": ["id"],
    "hello": ["fw", "caps"],
}
LIGHT_MODES = {"off", "idle", "listen", "think", "speak", "alert", "sleep", "charge"}

# ---------------------------------------------------------------------------
# PROTOCOL.md §2 — Pi <-> head ESP32 ("face"), USB CDC serial, 921600 baud
# ---------------------------------------------------------------------------
PI_TO_FACE = {
    "mood": ["m"],
    "gaze": ["x", "y"],
    "blink": [],
    "ears": [],          # either l + r, or wiggle: true
    "visor": ["open"],
    "bright": ["b"],
}
FACE_TO_PI = {
    "visor": ["state"],
    "touch": ["g"],
    "range": ["head_mm"],  # 10 Hz forward ToF at head height: -1 = no reading, 4000 = clear
    "hello": ["fw"],
}
MOODS = {"neutral", "happy", "curious", "thinking", "sad", "surprised", "sleepy",
         "asleep", "confused", "listening"}
VISOR_STATES = {"open", "closed", "moving", "jammed"}

# ---------------------------------------------------------------------------
# PROTOCOL.md §3 — body agent (Pi) <-> mind (K8), WebSocket ws://k8:8765/body
# ---------------------------------------------------------------------------
BODY_TO_MIND = {
    "hello": ["body_id", "fw", "caps"],
    "heard": ["text", "speaker", "doa", "conf", "id"],
    "saw": ["people", "ts"],
    "touch": ["g"],
    "state": ["battery_pct", "charging", "docked", "place", "fault", "quiet_hours"],
    "event": ["e", "detail"],
    "tool_result": ["call_id", "ok"],
}
MIND_TO_BODY = {
    "tool_call": ["call_id", "name", "args"],
    "listen": ["seconds"],
    "speak_state": ["on"],
}
# Tools the body executes when the mind sends a `tool_call` (PROTOCOL.md §3).
BODY_TOOLS = ["say", "express", "look", "turn_to", "go_to", "approach", "dock",
              "sleep", "wake", "stop"]


class ProtocolError(ValueError):
    """Raised by make() when a message we are about to SEND is malformed."""


def make(table: dict, t: str, **fields) -> dict:
    """Build a message of type `t`, checking required fields against `table`.

    Example: make(PI_TO_BASE, "vel", v=0.1, w=0.0, seq=7)
    """
    if t not in table:
        raise ProtocolError(f"unknown message type {t!r} for this link")
    missing = [name for name in table[t] if name not in fields]
    if missing:
        raise ProtocolError(f"{t!r} message is missing {missing}")
    return {"t": t, **fields}


def encode(msg: dict) -> str:
    """Encode one message as a JSON string (no trailing newline).

    json.dumps escapes any newline inside a string, so the output is always a
    single line and safe to frame with "\n" on serial.
    """
    if "t" not in msg:
        raise ProtocolError("every message needs a 't' field")
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":"))


def encode_line(msg: dict) -> bytes:
    """Encode one message for a serial link: UTF-8 JSON plus "\n"."""
    return (encode(msg) + "\n").encode("utf-8")


def decode(raw: str | bytes, table: dict | None = None) -> dict | None:
    """Decode one received message. Returns None if it should be ignored.

    Ignored (logged at debug level, never raised):
      - empty lines, bytes that are not UTF-8, text that is not JSON
      - JSON that is not an object, or has no string "t" field
      - with `table` given: unknown types, or known types missing a required field
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            log.debug("ignoring non-UTF-8 line")
            return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("ignoring non-JSON line: %.80s", raw)
        return None
    if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
        log.debug("ignoring message without a 't' field: %.80s", raw)
        return None
    if table is not None:
        if msg["t"] not in table:
            log.debug("ignoring unknown message type %r", msg["t"])
            return None
        missing = [name for name in table[msg["t"]] if name not in msg]
        if missing:
            log.debug("ignoring %r message missing %s", msg["t"], missing)
            return None
    return msg
