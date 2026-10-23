"""A pretend Home Assistant for the simulator: canned states served in-process.
No network. Used by `python -m mind --fake-llm` and `python -m body.sim --with-fake-mind`."""

from __future__ import annotations

import httpx2

FAKE_HA_URL = "http://fake-home-assistant.invalid"

STATES = [
    {"entity_id": "binary_sensor.back_door", "state": "off", "last_changed": "2026-10-23T07:12:00+08:00",
     "attributes": {"friendly_name": "Back door", "device_class": "door"}},
    {"entity_id": "binary_sensor.front_door", "state": "off", "last_changed": "2026-10-23T08:30:00+08:00",
     "attributes": {"friendly_name": "Front door", "device_class": "door"}},
    {"entity_id": "sensor.outdoor_temperature", "state": "24.5", "last_changed": "2026-10-23T09:55:00+08:00",
     "attributes": {"friendly_name": "Outdoor temperature", "unit_of_measurement": "°C"}},
    {"entity_id": "binary_sensor.raining", "state": "off", "last_changed": "2026-10-23T06:00:00+08:00",
     "attributes": {"friendly_name": "Raining"}},
    {"entity_id": "light.lounge", "state": "on", "last_changed": "2026-10-23T18:00:00+08:00",
     "attributes": {"friendly_name": "Lounge light"}},
    {"entity_id": "camera.driveway", "state": "idle", "last_changed": "x",
     "attributes": {"friendly_name": "Driveway camera"}},
]


def transport() -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method != "GET":
            return httpx2.Response(405)
        if request.url.path == "/api/states":
            return httpx2.Response(200, json=STATES)
        entity = request.url.path.removeprefix("/api/states/")
        match = [s for s in STATES if s["entity_id"] == entity]
        return httpx2.Response(200, json=match[0]) if match else httpx2.Response(404)
    return httpx2.MockTransport(handler)
