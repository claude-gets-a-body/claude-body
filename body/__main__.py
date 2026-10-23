"""Run the body agent on the robot.

    BODY_TOKEN=... python -m body --config /etc/claude-body/body.toml

Which drivers are used (real serial ESP32s, OpenCV camera, simulated nav, ...)
comes from the config file. Until the real voice pipeline exists, set
voice_driver = "console" to type what the robot hears (useful for bench tests
of the head on its stand).

For the no-hardware simulator, use `python -m body.sim` instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from common.clock import Clock

from .build import build
from .config import load as load_config


async def run(config_path: str | None) -> None:
    cfg = load_config(config_path)
    if not cfg.body_token:
        raise SystemExit("BODY_TOKEN is not set in the environment.")
    clock = Clock()
    body = build(cfg, clock)
    if cfg.voice_driver == "console":
        from .sim import console
        runner = asyncio.create_task(body.run())
        try:
            await console(body, clock)
        finally:
            runner.cancel()
            await body.agent.close()
    else:
        await body.run()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m body", description="Claude's body agent (runs on the Pi).")
    p.add_argument("--config", help="body TOML config")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(args.config))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
