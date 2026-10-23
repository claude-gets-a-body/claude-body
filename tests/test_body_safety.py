"""Rules the BODY enforces: visor-gated camera, head position before a photo,
quiet hours, keep-out and bedroom windows, no-look regions, stop words, speed
near people, the head-height range sensor, the 10 Hz vel heartbeat, and
anonymous people (no face recognition)."""

import asyncio

import pytest

from body.build import build
from body.config import BodyConfig, Place
from body.drivers.camera import FolderCamera, VisorClosed
from body.drivers.voice import Utterance
from body.safety import stop_words
from body.sim import parse_people
from tests.conftest import PROJECT, perth


def make_body(clock, **overrides):
    settings = dict(base_driver="sim", face_driver="sim", camera_driver="folder", nav_driver="sim",
                    voice_driver="console", sim_frames_dir=str(PROJECT / "sim_frames"), sim_time_scale=200.0)
    settings.update(overrides)
    return build(BodyConfig(**settings), clock, out=lambda *a: None)


async def speak(body, text="come here", doa=0.0):
    await body.agent.on_utterance(Utterance(text, speaker=None, doa=doa))


# ------------------------------------------------------------------ the visor
def test_camera_refuses_unless_visor_reported_open():
    state = {"visor": "closed"}
    cam = FolderCamera(lambda: state["visor"] == "open", PROJECT / "sim_frames")
    for s in ("closed", "moving", "jammed"):
        state["visor"] = s
        with pytest.raises(VisorClosed):
            cam.capture_jpeg()
    state["visor"] = "open"
    assert cam.capture_jpeg()[:2] == b"\xff\xd8"


async def test_look_refused_when_visor_jams_and_camera_never_read(clock):
    body = make_body(clock)
    body.face.jam = True
    grabbed = []
    body.agent.camera._grab = lambda hint: grabbed.append(1) or b"x"
    reply = await body.agent.execute("look", {})
    assert reply["ok"] is False and "visor didn't open" in reply["error"]
    assert grabbed == [] and "image_b64" not in reply
    assert body.face.sent[-1] == {"t": "visor", "open": False}        # told to close again


async def test_look_waits_for_head_then_opens_visor_and_closes_after(clock):
    body = make_body(clock)
    body.base.head_seconds = 0.4                 # slow neck
    order = []
    real_visor = body.face.visor

    async def visor(open_):
        order.append(("visor", open_, body.base.state["pan"]))
        await real_visor(open_)

    body.face.visor = visor
    reply = await body.agent.execute("look", {"at": "left"})
    assert reply["ok"] and reply["image_b64"]
    assert order[0] == ("visor", True, 60), "visor opened only after the head reached pan 60"
    assert order[1][:2] == ("visor", False)
    await asyncio.sleep(0.3)
    assert body.face.visor_state == "closed"


async def test_look_refused_if_head_never_gets_there(clock):
    body = make_body(clock)
    body.base.head_stuck = True
    reply = await body.agent.execute("look", {"at": "right"})
    assert not reply["ok"] and "head didn't reach" in reply["error"]
    assert not [m for m in body.face.sent if m["t"] == "visor" and m["open"]], "visor never opened"


async def test_tilt_is_clamped_to_minus15_plus30_in_one_place(clock):
    body = make_body(clock)
    assert await body.base.head(0, 45) == (0, 30)
    assert await body.base.head(0, -20) == (0, -15)
    assert await body.base.head(200, 0) == (150, 0)
    await body.agent.execute("look", {"at": "up"})
    ups = [m for m in body.base.sent_of("head")]
    assert ups[-1]["tilt"] == 28
    assert all(-15 <= m["tilt"] <= 30 for m in body.base.sent_of("head"))


async def test_stop_looking_hold_and_no_look_regions(clock):
    body = make_body(clock)
    await body.agent.on_utterance(Utterance("stop looking at me"))
    reply = await body.agent.execute("look", {})
    assert not reply["ok"] and "stop looking" in reply["error"]
    clock.advance(minutes=3)
    assert (await body.agent.execute("look", {}))["ok"]

    nav = body.agent.nav
    nav.place = "bathroom"                                   # in a no-look region
    r = await body.agent.execute("look", {})
    assert not r["ok"] and "never open my visor in the bathroom" in r["error"]

    # moving between rooms: the region is unknown; refuse if either end is no-look
    nav.moving, nav.origin, nav.destination = True, "bathroom", "hallway"
    assert nav.current_region() is None
    r = await body.agent.execute("look", {})
    assert not r["ok"] and "on my way to or from the bathroom" in r["error"]
    nav.origin = "kitchen"
    assert (await body.agent.execute("look", {}))["ok"], "moving between ordinary rooms is fine"
    nav.moving = False


# ---------------------------------------------------------------- quiet hours
@pytest.mark.parametrize("hhmm,quiet", [("20:59", False), ("21:00", True), ("22:30", True),
                                        ("02:00", True), ("06:59", True), ("07:00", False)])
async def test_quiet_hours_refuse_driving(clock, hhmm, quiet):
    h, m = map(int, hhmm.split(":"))
    clock.set(perth(2026, 10, 23, h, m))
    body = make_body(clock)
    body.agent.perception.set_people([{"bearing": 0, "dist_m": 3.0}])
    await speak(body)
    go = await body.agent.execute("go_to", {"place": "kitchen"})
    near = await body.agent.execute("approach", {})
    if quiet:
        assert not go["ok"] and "quiet hours" in go["error"]
        assert not near["ok"] and "quiet hours" in near["error"]
        assert [v for v in body.base.sent_of("vel") if v["v"] or v["w"]] == [], "no wheel motion in quiet hours"
    else:
        assert go["ok"], go
        assert near["ok"], near


async def test_dock_allowed_in_quiet_hours_but_obeys_stop(clock):
    clock.set(perth(2026, 10, 23, 22, 30))
    body = make_body(clock)
    body.agent.nav.docked = False
    body.agent.nav.place = "lounge"
    await body.agent.on_utterance(Utterance("stop"))
    r = await body.agent.execute("dock", {})
    assert not r["ok"] and "told to stop" in r["error"]
    clock.advance(seconds=11)
    assert (await body.agent.execute("dock", {}))["ok"]
    vel_before = len(body.base.sent_of("vel"))
    turned = await body.agent.execute("turn_to", {"target": "120"})
    assert turned["ok"] and turned["result"]["turned"] == "head"
    assert len(body.base.sent_of("vel")) == vel_before


async def test_say_is_quiet_in_quiet_hours(clock):
    clock.set(perth(2026, 10, 23, 23, 0))
    body = make_body(clock)
    lines = []
    body.agent.voice.out = lines.append
    await body.agent.execute("say", {"text": "Shh, it's late."})
    assert any("quietly" in l for l in lines)


# ------------------------------------------------------- places and bedrooms
async def test_keep_out_and_unknown_places(clock):
    body = make_body(clock)
    for place in ("bathroom", "the Bathroom", "outside", "garage", "main bedroom", "child 1 bedroom"):
        r = await body.agent.execute("go_to", {"place": place})
        assert not r["ok"] and "keep-out" in r["error"], place
    r = await body.agent.execute("go_to", {"place": "the moon"})
    assert not r["ok"] and "don't know a place" in r["error"]


async def test_bedroom_enabled_by_parent_with_time_window(clock):
    body = make_body(clock)
    body.agent.cfg.places["child 1 bedroom"] = Place(kind="normal", windows=["15:30-19:00"])
    clock.set(perth(2026, 10, 23, 10, 0))
    r = await body.agent.execute("go_to", {"place": "child 1 bedroom"})
    assert not r["ok"] and "15:30-19:00" in r["error"]
    clock.set(perth(2026, 10, 23, 16, 0))
    assert (await body.agent.execute("go_to", {"place": "child 1 bedroom"}))["ok"]
    body.agent.cfg.places["study"] = Place(kind="normal")           # no windows: any time (outside quiet hours)
    assert (await body.agent.execute("go_to", {"place": "study"}))["ok"]


# --------------------------------------------------------------- stop words
@pytest.mark.parametrize("text,expected", [
    ("stop!", ["stop"]), ("Claude STOP right there", ["stop"]), ("stop looking at me", ["stop_looking"]),
    ("go away please", ["go_away"]), ("close your eyes", ["stop_looking"]),
    ("what's the weather", []), ("stop looking and go away", ["stop_looking", "go_away"]),
])
def test_stop_word_detection(text, expected):
    assert stop_words(text) == expected


async def test_stop_halts_immediately(clock):
    body = make_body(clock, sim_time_scale=0.5)        # slow drive so we can interrupt it
    drive = asyncio.create_task(body.agent.execute("go_to", {"place": "kitchen"}))
    await asyncio.sleep(0.25)
    assert body.agent.motion.moving
    await body.agent.on_utterance(Utterance("stop!"))
    result = await asyncio.wait_for(drive, 2)
    assert not result["ok"] and "cancelled" in result["error"]
    assert not body.agent.motion.moving
    assert body.base.sent_of("stop"), "base got an explicit stop"
    assert body.base.sent_of("vel")[-1]["v"] == 0.0
    again = await body.agent.execute("go_to", {"place": "kitchen"})
    assert not again["ok"] and "told to stop" in again["error"]


async def test_go_away_blocks_approach(clock):
    body = make_body(clock)
    body.agent.perception.set_people([{"bearing": 0, "dist_m": 3.0}])
    await speak(body, "go away")
    r = await body.agent.execute("approach", {})
    assert not r["ok"] and "go away" in r["error"]


# -------------------------------------------------- approach by voice + lidar
async def test_approach_drives_towards_the_voice_and_stops_at_one_metre(clock):
    body = make_body(clock)
    body.agent.perception.set_people([{"bearing": 40, "dist_m": 2.5}, {"bearing": -60, "dist_m": 1.5}])
    r = await body.agent.execute("approach", {})
    assert not r["ok"] and "by their voice" in r["error"], "nobody has spoken yet"

    await speak(body, "come here", doa=40)
    assert body.agent.perception.nearest_return(body.agent.last_bearing) == 2.5
    distances = []
    real = body.agent.nav.approach

    async def spy(bearing, dist, stop_at):
        distances.append((bearing, dist, stop_at))
        return await real(bearing, dist, stop_at)

    body.agent.nav.approach = spy
    r = await body.agent.execute("approach", {"person": "whoever"})
    assert r["ok"] and r["result"]["stopped_at_m"] == 1.0 and r["result"]["bearing"] == 40
    assert distances == [(40.0, 2.5, 1.0)], "drives towards the voice, not the nearer person"
    assert max(abs(v["v"]) for v in body.base.sent_of("vel")) <= 0.12

    clock.advance(seconds=31)
    r = await body.agent.execute("approach", {})
    assert not r["ok"] and "by their voice" in r["error"], "the voice is too old to trust"


async def test_approach_already_close(clock):
    body = make_body(clock)
    body.agent.perception.set_people([{"bearing": 0, "dist_m": 0.9}])
    await speak(body, doa=0)
    r = await body.agent.execute("approach", {})
    assert r["ok"] and "already close" in r["result"]["detail"]


def test_people_are_anonymous_and_speaker_only_from_sim():
    assert parse_people("Nick 1.2 left, 2 ahead") == [
        {"name": None, "bearing": 60.0, "dist_m": 1.2}, {"name": None, "bearing": 0.0, "dist_m": 2.0}]
    from body.drivers.perception import Perception
    p = Perception()
    p.set_people([{"name": "Nick", "bearing": 10, "dist_m": 1}])
    assert p.people[0]["name"] is None
    from body.drivers.voice import LocalVoice
    assert LocalVoice().identify_speaker(b"audio") is None


# -------------------------------------------------- speed + heartbeat
async def test_vel_heartbeat_is_10hz_while_moving(clock):
    body = make_body(clock)
    loop = asyncio.get_running_loop()
    times = []
    original = body.base._send

    async def stamp(msg):
        if msg["t"] == "vel":
            times.append(loop.time())
        await original(msg)

    body.base._send = stamp
    await body.agent.motion.drive(0.2, 0.0)
    await asyncio.sleep(1.0)
    await body.agent.motion.halt()
    vels = body.base.sent_of("vel")
    assert 9 <= len(vels) <= 13, len(vels)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert max(gaps[:-1]) < 0.2, "base watchdog needs >= 5 Hz"       # last gap is the halt
    assert [v["seq"] for v in vels] == sorted({v["seq"] for v in vels})
    assert vels[-1]["v"] == 0.0
    sent_before = len(body.base.sent_of("vel"))
    await asyncio.sleep(0.3)
    assert len(body.base.sent_of("vel")) == sent_before, "goes quiet after halt"


async def test_speed_capped_near_people(clock):
    body = make_body(clock)
    await body.agent.motion.drive(0.25, 0.0)
    await asyncio.sleep(0.15)
    assert body.base.sent_of("vel")[-1]["v"] == 0.25
    body.agent.perception.set_people([{"bearing": 10, "dist_m": 0.8}])
    await asyncio.sleep(0.25)
    assert body.base.sent_of("vel")[-1]["v"] == 0.12
    assert body.base.sent_of("limits")[-1]["v_max"] == 0.12
    await body.agent.motion.drive(5.0, 9.0)      # asks for silly speeds
    await asyncio.sleep(0.15)
    last = body.base.sent_of("vel")[-1]
    assert last["v"] == 0.12 and last["w"] == 1.5
    await body.agent.motion.halt()


# ------------------------------------------- head-height range sensor (face ToF)
async def test_head_range_slows_then_stops_forward_motion(clock):
    body = make_body(clock)
    motion = body.agent.motion
    await motion.drive(0.25, 0.0)
    await asyncio.sleep(0.15)
    assert body.base.sent_of("vel")[-1]["v"] == 0.25

    body.face.set_head_range(250)                 # < 300 mm: slow
    await asyncio.sleep(0.15)
    assert motion.head_zone == "slow"
    assert body.base.sent_of("vel")[-1]["v"] == 0.05
    assert body.base.sent_of("limits")[-1]["v_max"] == 0.05

    stops_before = len(body.base.sent_of("stop"))
    body.face.set_head_range(120)                 # < 150 mm: stop
    await asyncio.sleep(0.15)
    assert motion.head_zone == "block"
    assert len(body.base.sent_of("stop")) == stops_before + 1
    assert body.base.sent_of("vel")[-1]["v"] == 0.0

    await motion.drive(-0.1, 0.0)                 # reversing away is allowed
    await asyncio.sleep(0.15)
    assert body.base.sent_of("vel")[-1]["v"] == -0.1
    await motion.halt()

    body.face.set_head_range(4000)                # clear again
    await asyncio.sleep(0.05)
    assert motion.head_zone == "clear" and motion.forward_cap() == 0.25


async def test_no_head_reading_counts_as_slow(clock):
    body = make_body(clock)
    body.face.set_head_range(-1)
    await asyncio.sleep(0.05)
    assert body.agent.motion.head_zone == "slow" and body.agent.motion.forward_cap() == 0.05
    from body.drivers.face import FaceLink
    assert FaceLink().head_mm == -1, "real hardware starts as 'no reading' until the face reports"


async def test_head_blocked_refuses_go_to_and_approach_and_aborts_a_drive(clock):
    body = make_body(clock, sim_time_scale=0.5)
    body.face.set_head_range(100)
    await asyncio.sleep(0.05)
    r = await body.agent.execute("go_to", {"place": "kitchen"})
    assert not r["ok"] and "head-height" in r["error"]
    await speak(body)
    r = await body.agent.execute("approach", {})
    assert not r["ok"] and "head-height" in r["error"]

    body.face.set_head_range(4000)
    await asyncio.sleep(0.05)
    drive = asyncio.create_task(body.agent.execute("go_to", {"place": "kitchen"}))
    await asyncio.sleep(0.2)
    body.face.set_head_range(140)                # a benchtop appears in front of the face
    r = await asyncio.wait_for(drive, 2)
    assert not r["ok"] and "head-height" in r["error"]
    assert not body.agent.motion.moving


async def test_head_faces_forward_while_driving(clock):
    body = make_body(clock, sim_time_scale=0.5)
    drive = asyncio.create_task(body.agent.execute("go_to", {"place": "kitchen"}))
    await asyncio.sleep(0.2)
    await body.agent.execute("turn_to", {"target": "90"})
    await body.agent.execute("look", {"at": "left"})
    pans = [m["pan"] for m in body.base.sent_of("head")]
    assert pans[0] == 0, "head pointed forward before driving"
    assert all(abs(p) <= 20 for p in pans), pans
    body.agent.nav.cancel()
    await drive


# -------------------------------------------------- events to the mind
async def test_base_events_sent_at_most_once_a_minute_per_type(clock):
    body = make_body(clock)
    sent = []

    async def fake_send(t, **fields):
        sent.append((t, fields.get("e")))

    body.agent._send = fake_send
    for _ in range(5):
        body.base.inject_event("bump_l")
        body.base.inject_event("drop_l")
    body.base.inject_event("drop_rear")
    await asyncio.sleep(0.05)
    assert sent == [("event", "bump"), ("event", "drop")]
    body.agent._event_sent_at = {k: v - 61 for k, v in body.agent._event_sent_at.items()}
    body.base.inject_event("bump_r")
    await asyncio.sleep(0.05)
    assert sent[-1] == ("event", "bump")
