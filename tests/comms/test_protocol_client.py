"""Unit tests for the drDRO line-protocol client.

Pure parsing/framing is tested directly; the async transaction layer is tested against a
``FakeSerial`` that frames responses exactly like the firmware (key=value lines + crc=HH +
blank line), so CRC verification, retry, error pass-through, and link-state all run end-to-end
without hardware.
"""
import asyncio

from dro.comms.protocol_client import (
    ProtocolClient,
    Response,
    frame_request,
    parse_response,
    xor8,
)


# ── pure helpers ─────────────────────────────────────────────────────
def test_xor8_known_vectors():
    assert xor8(b"") == 0
    assert xor8(b"set servo.max 720") == 0x70   # from protocol_design.md A.8 example


def test_frame_request_plain_and_checksum():
    assert frame_request("sta") == b"sta\r"
    body = "set servo.max 720"
    assert frame_request(body, checksum=True) == body.encode() + b"*70\r"


def _frame(body_lines: list[str]) -> list[str]:
    """Build the lines a reader would yield (body + crc), with a correct XOR-8 crc."""
    body = "".join(l + "\n" for l in body_lines)
    return body_lines + [f"crc={xor8(body.encode()):02X}"]


def test_parse_scalar_ok():
    r = parse_response(_frame(["servo.max=720"]))
    assert r and r.crc_ok and r.error is None
    assert r.text("servo.max") == "720"
    assert r.as_float("servo.max") == 720.0


def test_parse_array():
    r = parse_response(_frame(["scales.num=1,2,3,4"]))
    assert r.as_ints("scales.num") == [1, 2, 3, 4]


def test_parse_empty_success_is_crc00():
    # `set` success: empty body → crc over "" is 0x00.
    r = parse_response(["crc=00"])
    assert r and r.crc_ok and r.error is None and r.values == {}


def test_parse_error_is_healthy_frame_but_falsey():
    r = parse_response(_frame(["error=read-only"]))
    assert r.crc_ok is True          # link is fine
    assert r.error == "read-only"
    assert not r                     # but the command failed


def test_parse_crc_mismatch():
    r = parse_response(["servo.max=720", "crc=FF"])
    assert r.crc_ok is False and not r


def test_parse_incomplete_frame():
    r = parse_response(["servo.max=720"])   # no crc line (timeout/garble)
    assert r.crc_ok is False and not r


# ── FakeSerial framing exactly like the firmware ─────────────────────
class FakeSerial:
    """Minimal serial stand-in. ``responder(request_line) -> list[str]`` returns body lines
    (no crc); the fake appends a correct ``crc=HH`` and blank-line terminator."""

    def __init__(self, responder):
        self.responder = responder
        self._inq = b""
        self._wbuf = b""
        self.requests: list[str] = []

    def reset_input_buffer(self):
        self._inq = b""

    def flush(self):
        pass

    def write(self, data):
        self._wbuf += bytes(data)
        while True:
            pos = next((i for i, b in enumerate(self._wbuf) if b in (13, 10)), None)
            if pos is None:
                break
            line = self._wbuf[:pos].decode("ascii", "replace")
            self._wbuf = self._wbuf[pos + 1:]
            self._respond(line)
        return len(data)

    def _respond(self, line):
        body = line.rsplit("*", 1)[0] if "*" in line else line
        self.requests.append(body)
        out = self.responder(body)
        if out is None:
            return                       # simulate a dead link (no reply → timeout)
        frame = "".join(l + "\n" for l in out)
        frame += f"crc={xor8(frame.encode()):02X}\n\n"
        self._inq += frame.encode("ascii")

    def read(self, n=1):
        if not self._inq:
            return b""
        out, self._inq = self._inq[:n], self._inq[n:]
        return out

    def close(self):
        pass


def _board_responder():
    """A tiny firmware stand-in with a couple of writable fields."""
    state = {"servo.max": "720", "servo.acc": "120"}

    def responder(line):
        parts = line.split()
        if not parts:
            return ["error=empty command"]
        cmd = parts[0]
        if cmd == "version":
            return ["version=v0.4.2-test"]
        if cmd == "sta":
            return ["scales.pos=0,0,0,0", "scales.speed=0,0,0,0",
                    "servo.pos=0", "servo.speed=0", "servo.tgt=0", "servo.mode=0"]
        if cmd == "get":
            name = parts[1]
            return [f"{name}={state[name]}"] if name in state else ["error=unknown variable"]
        if cmd == "set":
            name, val = parts[1], parts[2]
            if name not in state:
                return ["error=unknown variable"]
            state[name] = val
            return []                    # empty success body
        return ["error=unknown command"]

    return responder


def _run(coro):
    return asyncio.run(coro)


async def _with_client(transport, fn, **kw):
    client = ProtocolClient(port="fake", transport=transport, **kw)
    try:
        return await fn(client)
    finally:
        await client.close()


def test_command_version_roundtrip():
    fake = FakeSerial(_board_responder())

    async def go(c):
        assert await c.version() == "v0.4.2-test"
        assert c.connected is True

    _run(_with_client(fake, go))


def test_sta_has_servo_fields():
    fake = FakeSerial(_board_responder())

    async def go(c):
        r = await c.sta()
        assert r.crc_ok
        for k in ("scales.pos", "scales.speed", "servo.pos", "servo.speed", "servo.tgt", "servo.mode"):
            assert k in r.values, k

    _run(_with_client(fake, go))


def test_set_roundtrip_and_formatting():
    fake = FakeSerial(_board_responder())

    async def go(c):
        assert await c.set("servo.max", 500.0)            # float → "500"
        assert (await c.get("servo.max")).text("servo.max") == "500"
        assert "set servo.max 500" in fake.requests

    _run(_with_client(fake, go))


def test_set_array_uses_index():
    seen = {}

    def responder(line):
        seen["last"] = line
        return []                                          # empty success

    fake = FakeSerial(responder)

    async def go(c):
        await c.set("scales.num", 7, idx=2)
        assert seen["last"] == "set scales.num 2 7"

    _run(_with_client(fake, go))


def test_real_error_not_retried():
    calls = {"n": 0}

    def responder(line):
        calls["n"] += 1
        return ["error=read-only"]

    fake = FakeSerial(responder)

    async def go(c):
        r = await c.set("servo.pos", 5)
        assert r.error == "read-only"
        assert calls["n"] == 1            # genuine error returned immediately, not retried
        assert c.connected is True        # link is healthy

    _run(_with_client(fake, go))


def test_glitch_error_is_retried():
    calls = {"n": 0}

    def responder(line):
        calls["n"] += 1
        # First attempt simulates a dropped leading byte → "unknown command"; then recovers.
        return ["error=unknown command"] if calls["n"] == 1 else ["version=v0.4.2-test"]

    fake = FakeSerial(responder)

    async def go(c):
        r = await c.command("version")
        assert r.text("version") == "v0.4.2-test"
        assert calls["n"] == 2            # retried once past the glitch

    _run(_with_client(fake, go))


def test_link_goes_down_after_max_errors():
    fake = FakeSerial(lambda line: None)   # never replies → every command times out

    async def go(c):
        for _ in range(c.max_errors):
            await c.command("version", timeout=0.05, retries=1)
        assert c.connected is False

    # start "connected" by first doing a good handshake on a live board, then kill it
    good = FakeSerial(_board_responder())

    async def go2(c):
        assert await c.version() == "v0.4.2-test"
        assert c.connected is True
        c._ser = fake                      # swap in the dead link
        for _ in range(c.max_errors):
            await c.command("version", timeout=0.05, retries=1)
        assert c.connected is False

    _run(_with_client(good, go2))
