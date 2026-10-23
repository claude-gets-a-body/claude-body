"""A JSON-lines serial link that keeps itself connected.

Used for both ESP32s (PROTOCOL.md §1 and §2): 921600 baud USB CDC, one JSON
object per line. If the cable is pulled or the board reboots, `run()` logs it,
waits, and reopens the port — it never gives up and never crashes the agent.

pyserial is blocking, so reads and writes run in worker threads via
asyncio.to_thread. The port name can be a device path (/dev/ttyACM0, or better
a /dev/serial/by-id/... path) or any pyserial URL; tests use "loop://".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

import serial

from common.protocol import decode, encode_line

log = logging.getLogger(__name__)

BACKOFF_S = [0.5, 1, 2, 5]


class LinkDown(ConnectionError):
    pass


class JsonSerialLink:
    def __init__(self, port: str, baud: int, incoming_table: dict,
                 on_message: Callable[[dict], None], name: str):
        self.port = port
        self.baud = baud
        self.table = incoming_table
        self.on_message = on_message
        self.name = name
        self._ser: serial.SerialBase | None = None
        self._write_lock = asyncio.Lock()
        self.reconnects = 0

    @property
    def connected(self) -> bool:
        return self._ser is not None

    def _open(self) -> serial.SerialBase:
        return serial.serial_for_url(self.port, baudrate=self.baud, timeout=0.2)

    async def run(self) -> None:
        attempt = 0
        while True:
            try:
                self._ser = await asyncio.to_thread(self._open)
                log.info("%s link open on %s", self.name, self.port)
                attempt = 0
                await self._read_loop()
            except (serial.SerialException, OSError) as e:
                if attempt == 0:
                    log.warning("%s link problem on %s: %s (will keep retrying)", self.name, self.port, e)
            finally:
                self._close()
            delay = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
            attempt += 1
            self.reconnects += 1
            await asyncio.sleep(delay)

    async def _read_loop(self) -> None:
        ser = self._ser
        buffer = b""
        while ser is self._ser:
            chunk = await asyncio.to_thread(ser.readline)
            if not chunk:
                continue
            buffer += chunk
            if not buffer.endswith(b"\n"):
                continue       # partial line; keep reading
            line, buffer = buffer, b""
            msg = decode(line, self.table)
            if msg is not None:
                try:
                    self.on_message(msg)
                except Exception:
                    log.exception("%s: error handling %s", self.name, msg.get("t"))

    def _close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    async def send(self, msg: dict) -> None:
        ser = self._ser
        if ser is None:
            raise LinkDown(f"{self.name} link is not connected")
        data = encode_line(msg)
        async with self._write_lock:
            try:
                await asyncio.to_thread(ser.write, data)
            except (serial.SerialException, OSError) as e:
                self._close()
                raise LinkDown(f"{self.name} write failed: {e}") from e
