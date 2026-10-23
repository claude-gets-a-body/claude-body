"""Mind <-> body over a REAL local WebSocket: tool_call out, tool_result back."""

import asyncio
import base64
import contextlib

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from body.build import build
from body.config import BodyConfig
from body.drivers.voice import Utterance
from mind import fake_house
from mind.app import Mind
from mind.fake_llm import FakeClaude, text_reply, tool_reply
from tests.conftest import PROJECT, wait_for


def body_cfg(url: str, token: str) -> BodyConfig:
    cfg = BodyConfig(mind_url=url, body_token=token, base_driver="sim", face_driver="sim",
                     camera_driver="folder", nav_driver="sim", voice_driver="console",
                     sim_frames_dir=str(PROJECT / "sim_frames"), sim_time_scale=200.0)
    return cfg


@contextlib.asynccontextmanager
async def running(mind_cfg, clock, fake):
    mind = Mind(mind_cfg, fake, clock=clock, house_transport=fake_house.transport())
    await mind.start()
    body = build(body_cfg(f"ws://127.0.0.1:{mind.port}/body", mind_cfg.body_token), clock, out=lambda *a: None)
    runner = asyncio.create_task(body.run())
    try:
        await asyncio.wait_for(body.agent.connected.wait(), 5)
        await wait_for(lambda: mind.link.connected)
        yield mind, body
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
        await body.agent.close()
        await mind.stop()


async def test_look_round_trip_sends_image_to_claude(mind_cfg, clock):
    fake = FakeClaude(script=[tool_reply("look", {"at": "ahead"}, "Let me look."),
                              text_reply("It's a beetle!")])
    async with running(mind_cfg, clock, fake) as (mind, body):
        body.agent.voice.hear(Utterance(text="Claude, what's this bug?", speaker="Sam", doa=10))
        await wait_for(lambda: len(fake.requests) == 2 and "It's a beetle!" in body.agent.voice.spoken)

        tool_results = fake.requests[1]["messages"][-1]["content"]
        result = tool_results[0]
        assert result["type"] == "tool_result" and not result.get("is_error")
        image = next(c for c in result["content"] if c["type"] == "image")
        assert image["source"]["media_type"] == "image/jpeg"
        assert base64.b64decode(image["source"]["data"])[:2] == b"\xff\xd8"      # a real JPEG
        # the visor went up for the photo and is back down
        visor_cmds = [m["open"] for m in body.face.sent if m["t"] == "visor"]
        assert visor_cmds[:2] == [True, False]
        assert body.face.visor_state in ("closed", "moving")
        assert "Let me look." in body.agent.voice.spoken
        assert fake.problems == []


async def test_go_to_round_trip_and_refusal_reaches_claude(mind_cfg, clock):
    fake = FakeClaude(script=[tool_reply("go_to", {"place": "kitchen"}), text_reply("Here!"),
                              tool_reply("go_to", {"place": "bathroom"}), text_reply("Sorry.")])
    async with running(mind_cfg, clock, fake) as (mind, body):
        body.agent.voice.hear(Utterance(text="go to the kitchen", speaker="Sam"))
        await wait_for(lambda: len(fake.requests) == 2)
        ok = fake.requests[1]["messages"][-1]["content"][0]
        assert not ok.get("is_error") and "kitchen" in ok["content"]
        assert body.agent.nav.place == "kitchen"
        assert body.base.sent_of("vel"), "driving must send vel heartbeats"

        body.agent.voice.hear(Utterance(text="go to the bathroom", speaker="Sam"))
        await wait_for(lambda: len(fake.requests) == 4)
        refused = fake.requests[3]["messages"][-1]["content"][0]
        assert refused["is_error"] and "keep-out" in refused["content"]
        assert fake.problems == []


async def test_heard_carries_body_bearing_and_state_reaches_mind(mind_cfg, clock):
    fake = FakeClaude(script=[text_reply("Hi!")])
    async with running(mind_cfg, clock, fake) as (mind, body):
        body.base.state["pan"] = 30.0                       # head turned 30 deg left
        body.agent.voice.hear(Utterance(text="hello", speaker=None, doa=20))   # voice 20 deg left of the head
        await wait_for(lambda: len(fake.requests) == 1)
        user = next(m for m in fake.requests[0]["messages"] if m["role"] == "user")
        assert "50° to your left" in user["content"]       # 20 + 30 = 50 relative to the body
        await wait_for(lambda: mind.engine.world.state.get("battery_pct") == 80)


async def test_bad_token_and_wrong_path_are_refused(mind_cfg, clock):
    mind = Mind(mind_cfg, FakeClaude(), clock=clock, house_transport=fake_house.transport())
    await mind.start()
    try:
        with pytest.raises(InvalidStatus) as e:
            async with connect(f"ws://127.0.0.1:{mind.port}/body",
                               additional_headers={"Authorization": "Bearer wrong"}):
                pass
        assert e.value.response.status_code == 401
        with pytest.raises(InvalidStatus) as e:
            async with connect(f"ws://127.0.0.1:{mind.port}/body"):
                pass
        assert e.value.response.status_code == 401
        with pytest.raises(InvalidStatus) as e:
            async with connect(f"ws://127.0.0.1:{mind.port}/elsewhere",
                               additional_headers={"Authorization": "Bearer test-token"}):
                pass
        assert e.value.response.status_code == 404
        assert not mind.link.connected
    finally:
        await mind.stop()


async def test_tool_call_times_out_when_body_never_answers(mind_cfg, clock):
    mind = Mind(mind_cfg, FakeClaude(), clock=clock, house_transport=fake_house.transport())
    await mind.start()
    try:
        async with connect(f"ws://127.0.0.1:{mind.port}/body",
                           additional_headers={"Authorization": "Bearer test-token"}):
            await wait_for(lambda: mind.link.connected)
            reply = await mind.link.call_tool("look", {}, timeout=0.3)
            assert reply["ok"] is False and "didn't answer" in reply["error"]
    finally:
        await mind.stop()
