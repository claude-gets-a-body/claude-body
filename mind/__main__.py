"""Run the mind.

    python -m mind --fake-llm            scripted pretend Claude (no key, no network)
    python -m mind --live                real Claude API (needs ANTHROPIC_API_KEY)
    python -m mind --live --brain claude_code
                                         a locked-down Claude Code process on a Claude
                                         plan (needs CLAUDE_CODE_OAUTH_TOKEN from
                                         `claude setup-token`); see mind/cc_brain.py

Options:
    --config path/to/mind.toml           settings (see config/mind.example.toml)
    --port 8765                          override the listening port
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from . import config as config_module
from .app import Mind

SIM_TOKEN = "sim-token"
SIM_CAP_USD = 10.0   # simulator only; never used with --live


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mind", description="Claude's mind (runs on K8).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fake-llm", action="store_true", help="use the scripted fake Claude")
    mode.add_argument("--live", action="store_true", help="use the real Claude API")
    parser.add_argument("--config", help="TOML settings file")
    parser.add_argument("--port", type=int)
    parser.add_argument("--brain", choices=["api", "claude_code"], help="override `brain` from the config")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_module.load(args.config)
    if args.port:
        cfg.port = args.port
    if args.brain:
        cfg.brain = args.brain

    house_transport = None
    if args.fake_llm:
        cfg.brain = "api"          # the fake stands in for the API; the claude_code brain has its own test fake
        from . import fake_house
        from .fake_llm import FakeClaude
        llm = FakeClaude()
        cfg.house.url = fake_house.FAKE_HA_URL      # never the real Home Assistant
        house_transport = fake_house.transport()
        if not cfg.body_token:
            cfg.body_token = SIM_TOKEN
            logging.info("BODY_TOKEN not set; using the simulator token %r", SIM_TOKEN)
        if cfg.budget.monthly_cap_usd is None:
            # Pretend money only: the fake Claude reports made-up token counts.
            cfg.budget.monthly_cap_usd = SIM_CAP_USD
            logging.info("no budget.monthly_cap_usd in config; the simulator uses a pretend "
                         "US$%.0f cap. --live refuses to start without a real one.", SIM_CAP_USD)
    elif cfg.brain == "claude_code":
        if not os.environ.get(cfg.claude_code.token_env):
            print(f"--brain claude_code needs {cfg.claude_code.token_env} in the environment "
                  "(make one with `claude setup-token`).", file=sys.stderr)
            return 2
        if not cfg.body_token:
            print("--live needs BODY_TOKEN in the environment.", file=sys.stderr)
            return 2
        if cfg.budget.monthly_cap_usd is None:
            cfg.budget.monthly_cap_usd = float("inf")   # plan usage isn't API money; it's logged, not capped
        from .cc_brain import ClaudeCodeBatchRunner
        llm = ClaudeCodeBatchRunner(cfg)                # used only by the nightly diary job
    else:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            print("--live needs ANTHROPIC_API_KEY in the environment.", file=sys.stderr)
            return 2
        if cfg.budget.monthly_cap_usd is None:
            print("--live needs budget.monthly_cap_usd (US$ per month) in the --config file.",
                  file=sys.stderr)
            return 2
        if not cfg.body_token:
            print("--live needs BODY_TOKEN in the environment (the body must send the same one).",
                  file=sys.stderr)
            return 2
        from .llm import ClaudeClient
        llm = ClaudeClient(api_key=key, timeout_s=cfg.claude.request_timeout_s)

    try:
        asyncio.run(Mind(cfg, llm, house_transport=house_transport).run_forever())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
