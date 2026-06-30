"""drDRO line-protocol client over RS-485.

Replaces the Modbus `ConnectionManager`. Talks the firmware's custom CLI line protocol
(see ../drdro-firmware-f4/docs/protocol_design.md):

  request  : ``command [args] [*HH]\\r``      (``*HH`` = optional XOR-8 hex of the body)
  response : ``key=value\\n`` lines, then ``crc=HH\\n`` (XOR-8 of the body), then a blank line.
             An ``error=<reason>`` line means the command failed.
  arrays   : one comma-joined line, e.g. ``scales.pos=12345,988,0,42``.

Concurrency (design D3): a single half-duplex bus means only one command may be outstanding
at a time. The public API is **async** and guarded by an :class:`asyncio.Lock`; the blocking
pyserial I/O runs in a dedicated single-thread executor, so the Kivy event loop is never
blocked. The protocol benches >100 Hz, leaving headroom to interleave ``set``/``get``/``save``
between 30 Hz ``sta`` polls.

Resilience mirrors the old ConnectionManager: a transient glitch does not bounce the link;
the connection is only declared down after ``max_errors`` consecutive failures. The RS-485
auto-direction transceiver can drop the firmware's first TX byte after a long RX, which can
make a valid command look like ``unknown command``/``unknown variable`` — those (and any
CRC/framing failure) are retried; genuine protocol errors (``read-only``, ``bad index``,
``value out of range``) are returned as-is.
"""
from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import serial

log = logging.getLogger(__name__)

# Errors that are likely an RS-485 turnaround glitch (dropped byte) rather than a real answer.
_GLITCH_ERRORS = frozenset({"unknown command", "unknown variable"})


def xor8(data: bytes) -> int:
    """NMEA-style XOR-8 checksum over ``data``."""
    c = 0
    for b in data:
        c ^= b
    return c


def frame_request(text: str, checksum: bool = False) -> bytes:
    """Encode a command line for the wire: optional ``*HH`` suffix, ``\\r`` terminated."""
    body = text.encode("ascii")
    if checksum:
        return body + b"*" + f"{xor8(body):02X}".encode("ascii") + b"\r"
    return body + b"\r"


@dataclass
class Response:
    """A parsed protocol response frame.

    ``crc_ok`` reflects link/frame health (a well-formed, checksum-valid reply was received),
    independent of ``error`` — a CRC-valid ``error=read-only`` is a healthy link with a
    negative answer. Truthiness = a valid frame with no ``error`` line.
    """

    lines: list[str] = field(default_factory=list)   # body lines incl. the trailing crc= line
    values: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    crc_ok: bool = False

    def __bool__(self) -> bool:
        return self.crc_ok and self.error is None

    # ── typed accessors ──────────────────────────────────────────────
    def text(self, key: str) -> str | None:
        return self.values.get(key)

    def as_int(self, key: str) -> int | None:
        v = self.values.get(key)
        return int(v) if v is not None else None

    def as_float(self, key: str) -> float | None:
        v = self.values.get(key)
        return float(v) if v is not None else None

    def as_ints(self, key: str) -> list[int]:
        v = self.values.get(key)
        return [int(x) for x in v.split(",")] if v else []

    def as_floats(self, key: str) -> list[float]:
        v = self.values.get(key)
        return [float(x) for x in v.split(",")] if v else []


def parse_response(lines: list[str]) -> Response:
    """Parse the lines of one frame (body lines incl. the trailing ``crc=HH`` line)."""
    if not lines or not lines[-1].startswith("crc="):
        # No terminating crc line → incomplete/garbled frame (timeout or glitch).
        values, error = _split_kv(lines)
        return Response(lines=lines, values=values, error=error, crc_ok=False)

    body = "".join(l + "\n" for l in lines[:-1])
    try:
        want = int(lines[-1].split("=", 1)[1], 16)
    except ValueError:
        want = -1
    crc_ok = want == xor8(body.encode("ascii"))

    values, error = _split_kv(lines[:-1])
    return Response(lines=lines, values=values, error=error, crc_ok=crc_ok)


def _split_kv(lines: list[str]) -> tuple[dict[str, str], str | None]:
    values: dict[str, str] = {}
    error: str | None = None
    for line in lines:
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        if key == "crc":
            continue
        if key == "error":
            error = val
        values[key] = val
    return values, error


def _read_frame(ser, timeout: float) -> list[str]:
    """Read one framed response: body ``key=value`` lines until a blank line.

    Returns the body lines *including* the trailing ``crc=HH`` line. On timeout returns
    whatever was collected (possibly empty/partial), which :func:`parse_response` flags
    as ``crc_ok=False``.
    """
    deadline = time.monotonic() + timeout
    buf = b""
    lines: list[str] = []
    seen = False
    while time.monotonic() < deadline:
        c = ser.read(1)
        if not c:
            continue
        if c == b"\n":
            line = buf.decode("ascii", "replace").replace("\r", "").strip()
            buf = b""
            if line == "":
                if seen:
                    return lines
                continue          # leading blank/glitch before any content
            seen = True
            lines.append(line)
        else:
            buf += c
    return lines


def _fmt(value) -> str:
    """Format a Python value for a ``set`` argument."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


class ProtocolError(Exception):
    """Raised for client-side protocol/usage errors (not firmware ``error=`` replies)."""


class ProtocolClient:
    """Async, lock-guarded client for the drDRO line protocol over a serial port."""

    def __init__(
        self,
        port: str | None = None,
        *,
        baudrate: int = 115200,
        byte_timeout: float = 0.25,
        command_timeout: float = 1.0,
        max_errors: int = 5,
        request_checksum: bool = False,
        transport=None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.byte_timeout = byte_timeout
        self.command_timeout = command_timeout
        self.max_errors = max_errors
        self.request_checksum = request_checksum

        self._ser = transport
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dro-serial")

        self._connected = False
        self._error_count = 0
        self._last_error: str | None = None

    # ── connection state (mirrors the old ConnectionManager semantics) ──
    @property
    def connected(self) -> bool:
        return self._connected

    def _mark_ok(self) -> None:
        if self._error_count:
            log.debug("Communication OK after %d error(s)", self._error_count)
        self._error_count = 0
        if not self._connected:
            self._connected = True
            self._last_error = None
            log.info("Communication restored with %s", self.port)

    def _mark_error(self, message: str) -> None:
        self._last_error = message
        self._error_count += 1
        if self._connected and self._error_count >= self.max_errors:
            self._connected = False
            log.warning(
                "Communication lost with %s after %d consecutive errors: %s",
                self.port, self._error_count, message,
            )

    # ── lifecycle ───────────────────────────────────────────────────
    async def open(self) -> None:
        if self._ser is not None:
            return
        loop = asyncio.get_running_loop()
        self._ser = await loop.run_in_executor(self._executor, self._open_serial)

    def _open_serial(self):
        return serial.Serial(self.port, self.baudrate, timeout=self.byte_timeout)

    async def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception as e:  # noqa: BLE001 — closing must not raise upward
                log.error("Error closing serial port: %s", e)
        self._executor.shutdown(wait=False)

    # ── core transaction ─────────────────────────────────────────────
    async def command(self, text: str, *, timeout: float | None = None, retries: int = 3) -> Response:
        """Send a command line and return its parsed :class:`Response` (serialized on the bus)."""
        if self._ser is None:
            raise ProtocolError("client not open")
        timeout = self.command_timeout if timeout is None else timeout
        async with self._lock:
            loop = asyncio.get_running_loop()
            resp = await loop.run_in_executor(
                self._executor, self._transact, text, timeout, retries
            )
        if resp.crc_ok:
            self._mark_ok()
        else:
            self._mark_error(self._last_error or "no valid frame")
        return resp

    async def run_blocking(self, fn):
        """Run ``fn(serial)`` on the executor thread holding the bus lock — for raw byte
        sequences (YMODEM) and multi-step bootloader flows that need exclusive serial access.
        The caller is responsible for pausing any concurrent polling (see Board.pause)."""
        if self._ser is None:
            raise ProtocolError("client not open")
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, fn, self._ser)

    def _transact(self, text: str, timeout: float, retries: int) -> Response:
        """Blocking write+read+retry. Runs on the executor thread."""
        last = Response()
        for attempt in range(max(1, retries)):
            try:
                self._ser.reset_input_buffer()
                self._ser.write(frame_request(text, self.request_checksum))
                self._ser.flush()
                lines = _read_frame(self._ser, timeout)
            except serial.SerialException as e:
                self._last_error = str(e)
                last = Response()
                break
            resp = parse_response(lines)
            last = resp
            if resp.crc_ok and resp.error not in _GLITCH_ERRORS:
                return resp
            # CRC/framing failure or a likely turnaround-glitch error → retry.
            self._last_error = (
                f"crc/framing fail (attempt {attempt + 1})" if not resp.crc_ok
                else f"glitch '{resp.error}' (attempt {attempt + 1})"
            )
            time.sleep(0.15)
        return last

    # ── convenience commands ─────────────────────────────────────────
    async def get(self, name: str) -> Response:
        return await self.command(f"get {name}")

    async def set(self, name: str, value, idx: int | None = None) -> Response:
        v = _fmt(value)
        text = f"set {name} {idx} {v}" if idx is not None else f"set {name} {v}"
        return await self.command(text)

    async def sta(self, *, timeout: float = 0.5) -> Response:
        return await self.command("sta", timeout=timeout)

    async def settings(self, *, timeout: float = 2.0) -> Response:
        return await self.command("settings", timeout=timeout)

    async def version(self) -> str | None:
        return (await self.command("version")).text("version")

    async def save(self) -> Response:
        return await self.command("save", timeout=2.0)

    async def load(self) -> Response:
        return await self.command("load", timeout=2.0)


async def _main(argv: list[str]) -> int:
    """Tiny CLI probe: ``python -m dro.comms.protocol_client /dev/ttyACM2 [command...]``."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(argv) < 2:
        print(__doc__)
        print("usage: python -m dro.comms.protocol_client <port> [command words...]")
        return 2
    port = argv[1]
    cmd = " ".join(argv[2:]) or "version"
    client = ProtocolClient(port)
    await client.open()
    try:
        resp = await client.command(cmd)
        print(f"connected={client.connected} crc_ok={resp.crc_ok} error={resp.error}")
        for k, v in resp.values.items():
            print(f"  {k}={v}")
    finally:
        await client.close()
    return 0 if resp else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(asyncio.run(_main(sys.argv)))
