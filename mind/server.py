"""The mind's WebSocket server (PROTOCOL.md §3): ws://k8:8765/body

- The body must connect to the right path and send
  "Authorization: Bearer <BODY_TOKEN>". Anything else gets HTTP 401/404 and never
  reaches the engine. If no token is configured, every connection is refused.
- One body at a time. If a second one connects, the first is closed.
- `call_tool()` sends a `tool_call` and waits for the matching `tool_result`,
  with a timeout. A timeout or a dropped connection comes back as ok: false,
  never as an exception, so a flaky Wi-Fi link can't crash a turn.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import uuid
from http import HTTPStatus

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from common.protocol import BODY_TO_MIND, MIND_TO_BODY, decode, encode, make

log = logging.getLogger(__name__)

MAX_FRAME_BYTES = 8 * 1024 * 1024   # a look photo is ~200 KB; leave lots of room


class BodyLink:
    def __init__(self, token: str, path: str = "/body", on_message=None):
        self.token = token
        self.path = path
        self.on_message = on_message or (lambda msg: None)
        self.ws: ServerConnection | None = None
        self.hello: dict | None = None
        self._waiting: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self.ws is not None

    # ------------------------------------------------------------ handshake
    def process_request(self, connection: ServerConnection, request):
        """Runs before the WebSocket upgrade. Returning a response refuses it."""
        if request.path != self.path:
            return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")
        if not self.token:
            log.error("refusing body connection: BODY_TOKEN is not set on the mind")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Mind has no BODY_TOKEN configured\n")
        sent = request.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        if not hmac.compare_digest(sent.encode(), expected.encode()):
            log.warning("refused a body connection with a bad or missing token")
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        return None

    # ------------------------------------------------------------ connection
    async def handler(self, ws: ServerConnection) -> None:
        if self.ws is not None:
            log.warning("a new body connected; closing the old connection")
            await self.ws.close(code=4000, reason="replaced by a new connection")
        self.ws = ws
        log.info("body connected from %s", ws.remote_address)
        try:
            async for raw in ws:
                msg = decode(raw, BODY_TO_MIND)
                if msg is None:
                    continue
                if msg["t"] == "tool_result":
                    fut = self._waiting.get(msg["call_id"])
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                    continue
                if msg["t"] == "hello":
                    self.hello = msg
                try:
                    self.on_message(msg)
                except Exception:
                    log.exception("error handling %s from body", msg["t"])
        except ConnectionClosed:
            pass
        finally:
            if self.ws is ws:
                self.ws = None
                for call_id, fut in list(self._waiting.items()):
                    if not fut.done():
                        fut.set_result({"t": "tool_result", "call_id": call_id, "ok": False,
                                        "error": "The body disconnected before finishing."})
            log.info("body disconnected")

    async def send(self, msg: dict) -> None:
        ws = self.ws
        if ws is None:
            raise ConnectionError("no body connected")
        await ws.send(encode(msg))

    async def call_tool(self, name: str, args: dict, timeout: float) -> dict:
        call_id = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiting[call_id] = fut
        try:
            try:
                await self.send(make(MIND_TO_BODY, "tool_call", call_id=call_id, name=name, args=args))
            except (ConnectionError, ConnectionClosed):
                return {"t": "tool_result", "call_id": call_id, "ok": False, "error": "The body isn't connected."}
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                return {"t": "tool_result", "call_id": call_id, "ok": False,
                        "error": f"The body didn't answer within {timeout:g} seconds."}
        finally:
            self._waiting.pop(call_id, None)


async def start_server(link: BodyLink, host: str, port: int):
    """Start listening. Returns the websockets Server (call .close() to stop)."""
    return await serve(link.handler, host, port, process_request=link.process_request,
                       max_size=MAX_FRAME_BYTES)
