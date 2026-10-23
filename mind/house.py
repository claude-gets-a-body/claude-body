"""Home Assistant, read only.

The robot may look at the house; it may never switch anything. That rule is
built into the shape of this file rather than left to good behaviour:

  - The only HTTP calls are GETs, to exactly two kinds of URL:
        GET /api/states
        GET /api/states/<entity_id>
  - There is no function here (or anywhere in the mind package) that sends a
    request with a body, calls a service, fires an event, or opens HA's
    websocket API. tests/test_house_readonly.py scans the source and fails the
    build if one ever appears.
  - Entities are filtered by an allow list and a deny list from the config, so
    things like cameras, people's locations, locks and the alarm stay unseen.
  - The token should be a dedicated one for the robot (see README-software.md).
"""

from __future__ import annotations

import fnmatch
import logging
import re

import httpx2  # the HTTP library the anthropic SDK already depends on (an httpx fork)

from .config import HouseConfig

log = logging.getLogger(__name__)

ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")

# Words that don't help match an entity ("is the back door open?" -> back, door, open)
STOPWORDS = {"is", "the", "a", "an", "are", "it", "on", "off", "in", "of", "what", "whats",
             "how", "any", "there", "outside", "inside", "house", "home", "now", "right",
             "please", "tell", "me", "check", "my", "our", "and", "or", "to"}


class HouseReader:
    def __init__(self, cfg: HouseConfig, token: str, transport: httpx2.AsyncBaseTransport | None = None):
        self.cfg = cfg
        # No token and no test transport -> never touch the network at all.
        self.configured = bool(token) or transport is not None
        self._client = httpx2.AsyncClient(
            base_url=cfg.url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            timeout=cfg.timeout_s,
            transport=transport,   # tests pass a fake transport; None = real network
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ---------------------------------------------------------------- filters
    def readable(self, entity_id: str) -> bool:
        if any(fnmatch.fnmatch(entity_id, pat) for pat in self.cfg.deny):
            return False
        return any(fnmatch.fnmatch(entity_id, pat) for pat in self.cfg.allow)

    # -------------------------------------------------------------- GET only
    async def _get_json(self, path: str):
        response = await self._client.get(path)
        response.raise_for_status()
        return response.json()

    async def all_states(self) -> list[dict]:
        states = await self._get_json("/api/states")
        return [s for s in states if self.readable(s.get("entity_id", ""))]

    async def state(self, entity_id: str) -> dict | None:
        if not ENTITY_ID.match(entity_id) or not self.readable(entity_id):
            return None
        return await self._get_json(f"/api/states/{entity_id}")

    # ------------------------------------------------------------ the tool
    @staticmethod
    def _summary(s: dict) -> str:
        attrs = s.get("attributes", {}) or {}
        name = attrs.get("friendly_name", s.get("entity_id"))
        unit = attrs.get("unit_of_measurement", "")
        value = f"{s.get('state')}{(' ' + unit) if unit else ''}"
        return f"{name} ({s.get('entity_id')}): {value}, last changed {s.get('last_changed', '?')}"

    async def answer(self, question: str, entity_ids: list[str] | None = None) -> str:
        """Find the entities that match the question and report their states.
        Claude reads the states and answers the person itself."""
        if not self.configured:
            return "Home Assistant isn't set up for me yet (no HA token), so I can't read the house."
        try:
            if entity_ids:
                found = []
                for eid in entity_ids[: self.cfg.max_results]:
                    s = await self.state(eid)
                    found.append(self._summary(s) if s else f"{eid}: not readable or not found")
                return "\n".join(found)

            states = await self.all_states()
            words = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if w not in STOPWORDS]
            scored = []
            for s in states:
                haystack = (s.get("entity_id", "") + " " +
                            str((s.get("attributes") or {}).get("friendly_name", ""))).lower()
                score = sum(1 for w in words if w in haystack)
                if score:
                    scored.append((score, s))
            scored.sort(key=lambda pair: -pair[0])
            if not scored:
                return ("No readable Home Assistant entity matched that. "
                        f"{len(states)} entities are readable; try different words.")
            return "\n".join(self._summary(s) for _, s in scored[: self.cfg.max_results])
        except httpx2.HTTPError as e:
            log.warning("Home Assistant read failed: %s", e)
            return f"Couldn't reach Home Assistant just now ({type(e).__name__})."
