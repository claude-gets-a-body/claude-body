"""Wires the mind together: server + engine + memory + nightly job."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from common.clock import Clock

from .budget import BudgetGovernor
from .config import PACKAGE_DIR, MindConfig
from .engine import Engine
from .house import HouseReader
from .memory_tool import MemoryStore
from .nightly import NightlyJob
from .server import BodyLink, start_server
from .timers import Timers
from .transcripts import TranscriptStore

log = logging.getLogger(__name__)


class Mind:
    def __init__(self, cfg: MindConfig, llm, clock: Clock | None = None, house_transport=None):
        self.cfg = cfg
        self.llm = llm
        self.clock = clock or Clock()
        state = Path(cfg.state_dir)
        state.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(cfg.memory_dir)
        self.memory.seed_from(cfg.memory_template_dir)
        self.transcripts = TranscriptStore(cfg.db_path)
        self.budget = BudgetGovernor(cfg.budget, cfg.db_path, alerts_path=state / "alerts.log")
        self.timers = Timers(cfg.db_path, now=self.clock.now)
        self.house = HouseReader(cfg.house, cfg.ha_token, transport=house_transport)
        self.link = BodyLink(cfg.body_token, cfg.path)
        system_text = (PACKAGE_DIR / "prompts" / "system.md").read_text(encoding="utf-8")
        self.engine = Engine(cfg, llm, self.link, self.memory, self.transcripts, self.house,
                             self.timers, self.budget, self.clock, system_text)
        self.link.on_message = self.engine.on_body_message
        nightly_prompt = (PACKAGE_DIR / "prompts" / "nightly.md").read_text(encoding="utf-8")
        self.nightly = NightlyJob(cfg, llm, self.memory, self.transcripts, self.budget, self.clock,
                                  nightly_prompt)
        self.server = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self.server = await start_server(self.link, self.cfg.host, self.cfg.port)
        self._tasks = [asyncio.create_task(self.engine.run(), name="engine"),
                       asyncio.create_task(self.nightly.run(), name="nightly")]
        log.info("mind listening on ws://%s:%d%s", self.cfg.host, self.cfg.port, self.cfg.path)

    @property
    def port(self) -> int:
        """The real port (useful when started with port 0 in tests)."""
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.engine.cc is not None:
            await self.engine.cc.close()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        await self.house.close()

    async def run_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Future()
        finally:
            await self.stop()
