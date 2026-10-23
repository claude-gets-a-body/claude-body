"""PROTOCOL.md framing: newline-delimited JSON with a "t" field; unknown types ignored."""

import asyncio
import json

import pytest

from body.drivers.serial_link import JsonSerialLink
from common.protocol import (BASE_TO_PI, BODY_TO_MIND, FACE_TO_PI, MIND_TO_BODY, PI_TO_BASE, PI_TO_FACE,
                             ProtocolError, decode, encode, encode_line, make)

EXAMPLES = [
    (PI_TO_BASE, make(PI_TO_BASE, "vel", v=0.1, w=-0.2, seq=7)),
    (PI_TO_BASE, make(PI_TO_BASE, "head", pan=30, tilt=10, speed=60)),
    (PI_TO_BASE, make(PI_TO_BASE, "light", mode="think", rgb=[255, 120, 0])),
    (PI_TO_BASE, make(PI_TO_BASE, "stop")),
    (BASE_TO_PI, {"t": "event", "e": "bump_l"}),
    (PI_TO_FACE, make(PI_TO_FACE, "visor", open=True)),
    (FACE_TO_PI, {"t": "visor", "state": "open"}),
    (BODY_TO_MIND, make(BODY_TO_MIND, "heard", text="what's this bug? 🐞", speaker=None, doa=-35.0, conf=0.9, id="u1")),
    (BODY_TO_MIND, make(BODY_TO_MIND, "tool_result", call_id="abc", ok=True, result={"x": 1}, image_b64="AAAA")),
    (MIND_TO_BODY, make(MIND_TO_BODY, "tool_call", call_id="abc", name="go_to", args={"place": "kitchen"})),
]


@pytest.mark.parametrize("table,msg", EXAMPLES)
def test_round_trip(table, msg):
    assert decode(encode(msg), table) == msg
    assert decode(encode_line(msg), table) == msg


def test_line_framing_is_one_line_even_with_newlines_in_text():
    msg = make(BODY_TO_MIND, "heard", text="line one\nline two", speaker="Sam", doa=0, conf=1, id="u2")
    line = encode_line(msg)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert decode(line, BODY_TO_MIND)["text"] == "line one\nline two"


@pytest.mark.parametrize("raw", [b"", b"   \n", b"not json\n", b"[1,2,3]\n", b'{"no_t": 1}\n',
                                 b"\xff\xfe garbage\n", b'{"t": 5}\n'])
def test_garbage_is_ignored_not_fatal(raw):
    assert decode(raw) is None


def test_unknown_type_ignored_with_table():
    assert decode('{"t": "teleport", "where": "moon"}', BASE_TO_PI) is None
    assert decode('{"t": "teleport"}') == {"t": "teleport"}      # without a table it's passed through


def test_received_message_missing_required_field_is_ignored():
    assert decode('{"t": "vel", "v": 0.1}', PI_TO_BASE) is None


def test_make_refuses_missing_fields_and_unknown_types():
    with pytest.raises(ProtocolError):
        make(PI_TO_BASE, "vel", v=0.1, w=0.0)
    with pytest.raises(ProtocolError):
        make(PI_TO_BASE, "dance")
    with pytest.raises(ProtocolError):
        encode({"no": "type"})


async def test_serial_link_framing_over_pyserial_loopback():
    """Bytes written by JsonSerialLink come back as the same messages (pyserial loop://)."""
    got = []
    link = JsonSerialLink("loop://", 921600, PI_TO_BASE, got.append, "test")
    runner = asyncio.create_task(link.run())
    try:
        for _ in range(100):
            if link.connected:
                break
            await asyncio.sleep(0.01)
        sent = [make(PI_TO_BASE, "vel", v=0.05 * i, w=0.0, seq=i) for i in range(5)]
        for m in sent:
            await link.send(m)
        for _ in range(200):
            if len(got) == 5:
                break
            await asyncio.sleep(0.01)
        assert got == [json.loads(json.dumps(m)) for m in sent]
    finally:
        runner.cancel()


async def test_serial_link_keeps_retrying_a_missing_port():
    link = JsonSerialLink("/dev/does-not-exist-claude", 921600, BASE_TO_PI, lambda m: None, "test")
    runner = asyncio.create_task(link.run())
    await asyncio.sleep(1.2)
    assert not link.connected and link.reconnects >= 2 and not runner.done()
    runner.cancel()
