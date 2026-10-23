"""Home Assistant must be read-only: no code path in the mind may switch anything.

Two kinds of check:
  1. A source scan of every .py file in mind/ (comments and docstrings ignored):
     no HA write endpoint strings, no HTTP verbs other than GET, no request
     methods that can send a body.
  2. A runtime check: HouseReader against a fake HA records every request; all
     must be GET /api/states[/<entity>], and filtered entities never come back.
"""

import ast
from pathlib import Path

import httpx2

from mind.config import HouseConfig
from mind.house import HouseReader

MIND = Path(__file__).resolve().parent.parent / "mind"

BANNED_URL_PARTS = ["/api/services", "/api/websocket", "/api/events", "/api/template",
                    "/api/config", "/api/intent", "/api/conversation"]
BANNED_METHOD_NAMES = {"post", "put", "patch", "delete", "request", "stream", "send_request"}
BANNED_VERB_STRINGS = {"POST", "PUT", "PATCH", "DELETE"}


def code_strings_and_calls(source: str):
    """All string constants (excluding docstrings) and all called attribute names."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    strings, calls = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            strings.append(node.value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.append(node.func.attr)
    return strings, calls


def mind_sources():
    files = sorted(MIND.rglob("*.py"))
    assert len(files) > 5, "scan found the mind package"
    return files


def test_no_home_assistant_write_paths_in_mind_source():
    problems = []
    for path in mind_sources():
        strings, calls = code_strings_and_calls(path.read_text(encoding="utf-8"))
        for s in strings:
            for bad in BANNED_URL_PARTS:
                if bad in s:
                    problems.append(f"{path.name}: string mentions {bad!r}")
            # Case-sensitive on purpose: "delete" is also the memory tool's own command
            # name. A lowercase HTTP verb could only be used through .request() /
            # .stream(), and those calls are banned below.
            if s.strip() in BANNED_VERB_STRINGS:
                problems.append(f"{path.name}: HTTP verb string {s!r}")
        for name in calls:
            if name in BANNED_METHOD_NAMES:
                problems.append(f"{path.name}: calls .{name}(...)")
    assert problems == [], "\n".join(problems)


def test_house_module_only_uses_get():
    source = (MIND / "house.py").read_text(encoding="utf-8")
    _, calls = code_strings_and_calls(source)
    http_calls = [c for c in calls if c in {"get", "post", "put", "patch", "delete", "request", "stream", "head"}]
    # .get(...) is also used on dicts; the point is nothing else appears
    assert set(http_calls) <= {"get"}
    strings, _ = code_strings_and_calls(source)
    api_paths = [s for s in strings if s.startswith("/api")]
    assert api_paths and all(p == "/api/states" or p.startswith("/api/states/") for p in api_paths), api_paths


def test_scanner_would_catch_a_service_call():
    """Make sure the scan isn't vacuous: a planted write call is detected."""
    bad = 'async def oops(c):\n    await c.post("/api/services/light/turn_on", json={})\n'
    strings, calls = code_strings_and_calls(bad)
    assert "post" in calls and any("/api/services" in s for s in strings)
    lower = 'async def oops(c):\n    await c.request("delete", "/api/states/light.x")\n'
    _, calls = code_strings_and_calls(lower)
    assert "request" in calls, "a lowercase verb still needs .request(), which is banned"


STATES = [
    {"entity_id": "binary_sensor.back_door", "state": "on",
     "attributes": {"friendly_name": "Back door"}, "last_changed": "2026-10-23T09:00:00+08:00"},
    {"entity_id": "sensor.outdoor_temperature", "state": "24.5",
     "attributes": {"friendly_name": "Outdoor temperature", "unit_of_measurement": "°C"}, "last_changed": "x"},
    {"entity_id": "camera.driveway", "state": "idle", "attributes": {"friendly_name": "Driveway door camera"}},
    {"entity_id": "lock.front_door", "state": "unlocked", "attributes": {"friendly_name": "Front door lock"}},
    {"entity_id": "cover.garage_door", "state": "closed", "attributes": {"friendly_name": "Garage door"}},
]


def fake_ha(seen: list):
    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.method != "GET":
            return httpx2.Response(405)
        if request.url.path == "/api/states":
            return httpx2.Response(200, json=STATES)
        entity = request.url.path.removeprefix("/api/states/")
        match = [s for s in STATES if s["entity_id"] == entity]
        return httpx2.Response(200, json=match[0]) if match else httpx2.Response(404)
    return httpx2.MockTransport(handler)


async def test_house_reader_only_gets_and_filters():
    seen = []
    reader = HouseReader(HouseConfig(url="http://ha.test:8123"), "tok", transport=fake_ha(seen))
    try:
        answer = await reader.answer("is the back door open?")
        assert "Back door" in answer and "on" in answer
        assert "camera" not in answer and "lock" not in answer and "Garage" not in answer

        temp = await reader.answer("how warm is it", ["sensor.outdoor_temperature", "lock.front_door"])
        assert "24.5 °C" in temp and "lock.front_door: not readable" in temp

        assert seen and all(method == "GET" for method, _, _ in seen)
        assert all(path == "/api/states" or path.startswith("/api/states/") for _, path, _ in seen)
        assert all(auth == "Bearer tok" for _, _, auth in seen)
        assert ("GET", "/api/states/lock.front_door", "Bearer tok") not in seen, "denied ids are never even fetched"
    finally:
        await reader.close()


async def test_house_reader_survives_ha_being_down():
    def handler(request):
        raise httpx2.ConnectError("no route to host")
    reader = HouseReader(HouseConfig(url="http://ha.test:8123"), "tok", transport=httpx2.MockTransport(handler))
    try:
        assert "Couldn't reach Home Assistant" in await reader.answer("is the back door open")
    finally:
        await reader.close()


async def test_unconfigured_house_never_touches_the_network():
    reader = HouseReader(HouseConfig(), "")           # no token, real transport
    try:
        answer = await reader.answer("is the back door open?")
        assert "isn't set up" in answer
    finally:
        await reader.close()


def test_network_guard_blocks_outside_connections():
    import socket
    s = socket.socket()
    try:
        import pytest
        with pytest.raises(ConnectionRefusedError, match="must not use the network"):
            s.connect(("192.0.2.10", 8123))
    finally:
        s.close()
