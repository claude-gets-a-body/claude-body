"""Shared test helpers. Nothing here touches the network, real hardware, or a real API."""

from __future__ import annotations

import asyncio
import socket
from datetime import datetime
from pathlib import Path

import pytest

from common.clock import PERTH, SimClock
from mind.config import MindConfig

PROJECT = Path(__file__).resolve().parent.parent

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test: refuse any connection that isn't to this machine. So no test can
    reach Home Assistant, the Claude API, or anything else real, even by accident."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in LOCAL_HOSTS:
            raise ConnectionRefusedError(f"test tried to reach {address!r}; tests must not use the network")

    def guarded(sock, address):
        check(sock, address)
        return real_connect(sock, address)

    def guarded_ex(sock, address):
        check(sock, address)
        return real_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_ex)


@pytest.fixture
def mind_cfg(tmp_path) -> MindConfig:
    cfg = MindConfig(host="127.0.0.1", port=0, state_dir=str(tmp_path / "state"),
                     memory_dir=str(tmp_path / "memories"), body_token="test-token")
    cfg.budget.monthly_cap_usd = 50.0
    cfg.ha_token = "not-a-real-token"
    return cfg


def perth(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=PERTH)


@pytest.fixture
def clock() -> SimClock:
    c = SimClock()
    c.set(perth(2026, 10, 23, 10, 0))     # a Friday morning, outside quiet hours
    return c


class FakeBody:
    """Stands in for the WebSocket link in engine tests."""

    def __init__(self, handlers: dict | None = None):
        self.connected = True
        self.calls: list[tuple[str, dict]] = []
        self.sent: list[dict] = []
        self.handlers = handlers or {}

    async def call_tool(self, name, args, timeout):
        self.calls.append((name, args))
        handler = self.handlers.get(name)
        if handler:
            return handler(args)
        return {"t": "tool_result", "call_id": "x", "ok": True, "result": {"done": name}}

    async def send(self, msg):
        self.sent.append(msg)


async def wait_for(condition, timeout=5.0, step=0.02):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not condition():
        if loop.time() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(step)


def make_engine(mind_cfg, clock, fake, body=None):
    """An Engine wired to a FakeBody (no WebSocket) and the fake Claude."""
    from mind import fake_house
    from mind.budget import BudgetGovernor
    from mind.config import PACKAGE_DIR
    from mind.engine import Engine
    from mind.house import HouseReader
    from mind.memory_tool import MemoryStore
    from mind.timers import Timers
    from mind.transcripts import TranscriptStore

    body = body or FakeBody()
    Path(mind_cfg.state_dir).mkdir(parents=True, exist_ok=True)
    mem = MemoryStore(mind_cfg.memory_dir)
    mem.seed_from(PACKAGE_DIR.parent / "memories")
    budget = BudgetGovernor(mind_cfg.budget, mind_cfg.db_path, now=clock.now)
    system_text = (PACKAGE_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
    engine = Engine(mind_cfg, fake, body, mem, TranscriptStore(mind_cfg.db_path),
                    HouseReader(mind_cfg.house, "", transport=fake_house.transport()), Timers(mind_cfg.db_path, clock.now),
                    budget, clock, system_text)
    return engine, body, budget


def heard(text, who="Sam", **extra):
    from mind.engine import Input
    return Input("heard", {"t": "heard", "text": text, "speaker": who, "doa": 0, "conf": 1, "id": "u", **extra})
