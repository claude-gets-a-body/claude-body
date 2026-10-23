"""The simulator: the whole robot in a terminal, no hardware, no API key.

    python -m mind --fake-llm          (terminal 1)
    python -m body.sim                 (terminal 2)

or both in one terminal:

    python -m body.sim --with-fake-mind

Type what the robot hears. Commands start with "/":

    /as Nick              the next things you type are said by Nick (/as alone = unknown).
                          This is the ONLY way a speaker gets a name: the real robot has
                          no face recognition and no voice-ID yet.
    /see 1.2 left         the lidar senses a person 1.2 m away to the left
                          (left / right / ahead, or an angle; several: "1.2 left, 2 ahead").
                          People are anonymous; a name typed first is ignored.
    /see nobody           nobody nearby
    /doa 40               your voice comes from 40 deg left of where the head points
                          ("come here" drives towards this direction)
    /head 120             the head-height range sensor reads 120 mm
                          (< 300 slow, < 150 stop; -1 = no reading; 4000 = clear)
    /pat  /hold  /double  touch the head pad
    /bump  /drop          base reflex events
    /battery 15           set the battery level
    /place kitchen        teleport the robot to a named place
    /time 22:30           pretend it's 22:30 (Perth); /time now to go back
    /state                show what the body would report
    /help  /quit
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from common.clock import SimClock

from .agent import BodyAgent
from .build import build
from .config import BodyConfig
from .config import load as load_config
from .drivers.voice import Utterance

SIDES = {"left": 60.0, "right": -60.0, "ahead": 0.0, "front": 0.0}


class SimAgent(BodyAgent):
    """Prints every tool call so you can see what the robot does."""

    async def execute(self, name: str, args: dict) -> dict:
        reply = await super().execute(name, args)
        if name == "say":
            return reply
        shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
        if reply.get("ok"):
            extra = ""
            if name == "look":
                extra = f" (photo: {self.camera.last_file.name}, {reply['result']['jpeg_bytes']} bytes)"
            print(f"  [body] {name}({shown}) -> ok{extra}")
        else:
            print(f"  [body] {name}({shown}) -> REFUSED: {reply.get('error')}")
        return reply


def _is_number(word: str) -> bool:
    try:
        float(word)
        return True
    except ValueError:
        return False


def parse_people(text: str) -> list[dict]:
    """'1.2 left, 2 ahead' -> list of anonymous people. A leading name
    ('Nick 1.2 left') is accepted and ignored: nobody is recognised by sight."""
    people = []
    for part in text.split(","):
        words = part.split()
        if not words or words[0].lower() in ("nobody", "none", "no-one"):
            continue
        if not _is_number(words[0]):
            words = words[1:]            # drop the name
        dist = float(words[0]) if words else 1.5
        side = words[1].lower() if len(words) > 1 else "ahead"
        bearing = SIDES.get(side)
        if bearing is None:
            bearing = float(side)
        people.append({"name": None, "bearing": bearing, "dist_m": dist})
    return people


async def console(body, clock: SimClock) -> None:
    agent = body.agent
    speaker: str | None = None
    doa = 0.0
    loop = asyncio.get_running_loop()
    print("Type what the robot hears (or /help). Waiting for the mind...")
    try:
        await asyncio.wait_for(agent.connected.wait(), 10)
        print("Connected to the mind.\n")
    except asyncio.TimeoutError:
        print("(not connected to the mind yet; is `python -m mind --fake-llm` running?)\n")

    while True:
        prompt = f"[{speaker or 'someone'}] > "
        try:
            line = await loop.run_in_executor(None, input, prompt)
        except (EOFError, KeyboardInterrupt):
            return
        line = line.strip()
        if not line:
            continue
        if not line.startswith("/"):
            agent.voice.hear(Utterance(text=line, speaker=speaker, doa=doa, conf=0.95))
            await asyncio.sleep(0.3)
            continue

        cmd, _, rest = line[1:].partition(" ")
        rest = rest.strip()
        try:
            if cmd in ("quit", "exit", "q"):
                return
            elif cmd == "help":
                print(__doc__)
            elif cmd == "as":
                speaker = rest or None
                print(f"  (now speaking as {speaker or 'an unknown person'})")
            elif cmd == "see":
                agent.perception.set_people(parse_people(rest))
                await asyncio.sleep(0.05)
                print(f"  (lidar senses: {agent.perception.people or 'nobody'}; speed limit "
                      f"{agent.motion.speed_limit} m/s)")
            elif cmd == "doa":
                doa = float(rest)
            elif cmd == "head":
                body.face.set_head_range(int(rest))
                await asyncio.sleep(0.05)
                print(f"  (head range {rest} mm -> {agent.motion.head_zone})")
            elif cmd in ("pat", "hold", "double"):
                body.face.touch(cmd)
            elif cmd == "bump":
                body.base.inject_event("bump_l", "front-left bumper")
            elif cmd == "drop":
                body.base.inject_event("drop_l", "step ahead on the left")
            elif cmd == "battery":
                body.base.state["bat_pct"] = int(rest)
                if int(rest) < 20:
                    body.base.inject_event("low_battery", f"{rest}%")
            elif cmd == "place":
                agent.nav.place = rest.lower() or None
                agent.nav.moving = False
                agent.nav.docked = rest.lower() == "dock"
                print(f"  (robot is now in: {agent.nav.place})")
            elif cmd == "time":
                if not isinstance(clock, SimClock):
                    print("  /time only works in the simulator")
                elif rest in ("", "now", "reset"):
                    clock.reset()
                else:
                    clock.set_time_of_day(rest)
                print(f"  (sim time {clock.now():%H:%M}; quiet hours: {agent.safety.quiet_hours()})")
            elif cmd == "state":
                print(f"  {agent.current_state()}")
            else:
                print("  unknown command; /help lists them")
        except (ValueError, IndexError) as e:
            print(f"  couldn't understand that: {e}")
        await asyncio.sleep(0.1)


async def run_sim(args) -> None:
    cfg: BodyConfig = load_config(args.config)
    cfg.base_driver = cfg.face_driver = "sim"
    cfg.camera_driver = "folder"
    cfg.nav_driver = "sim"
    cfg.voice_driver = "console"
    cfg.mind_url = args.mind
    if args.frames:
        cfg.sim_frames_dir = args.frames
    cfg.body_token = os.environ.get("BODY_TOKEN") or args.token
    clock = SimClock()
    body = build(cfg, clock, agent_class=SimAgent)
    body.face.verbose = True

    mind = None
    if args.with_fake_mind:
        from mind import fake_house
        from mind.app import Mind
        from mind.config import MindConfig
        from mind.fake_llm import FakeClaude

        state = Path(tempfile.mkdtemp(prefix="claude-body-sim-"))
        mcfg = MindConfig(host="127.0.0.1", port=0, state_dir=str(state), memory_dir=str(state / "memories"),
                          body_token=cfg.body_token)
        mcfg.budget.monthly_cap_usd = 10.0   # pretend money for the simulator
        mcfg.house.url = fake_house.FAKE_HA_URL
        mind = Mind(mcfg, FakeClaude(), clock=clock, house_transport=fake_house.transport())
        await mind.start()
        cfg.mind_url = f"ws://127.0.0.1:{mind.port}/body"
        print(f"(fake mind running in-process; its files are in {state})")

    runner = asyncio.create_task(body.run())
    try:
        await console(body, clock)
    finally:
        runner.cancel()
        await body.agent.close()
        if mind:
            await mind.stop()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m body.sim", description="Run the robot body in a terminal.")
    p.add_argument("--mind", default="ws://127.0.0.1:8765/body", help="mind WebSocket URL")
    p.add_argument("--token", default="sim-token", help="BODY_TOKEN (default matches `python -m mind --fake-llm`)")
    p.add_argument("--with-fake-mind", action="store_true", help="also run a fake mind in this process")
    p.add_argument("--frames", help="folder of sample JPEGs for `look`")
    p.add_argument("--config", help="body TOML config (places etc.)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run_sim(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
