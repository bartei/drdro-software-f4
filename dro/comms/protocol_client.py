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
    # A garbled value (line noise that slipped past the CRC, or read off a crc_ok=False
    # frame) yields None/[] rather than raising, so a bad message can never crash a caller.
    def text(self, key: str) -> str | None:
        return self.values.get(key)

    def as_int(self, key: str) -> int | None:
        v = self.values.get(key)
        try:
            return int(v) if v is not None else None
        except ValueError:
            log.warning("Malformed int for %r: %r", key, v)
            return None

    def as_float(self, key: str) -> float | None:
        v = self.values.get(key)
        try:
            return float(v) if v is not None else None
        except ValueError:
            log.warning("Malformed float for %r: %r", key, v)
            return None

    def as_ints(self, key: str) -> list[int]:
        v = self.values.get(key)
        try:
            return [int(x) for x in v.split(",")] if v else []
        except ValueError:
            log.warning("Malformed int array for %r: %r", key, v)
            return []

    def as_floats(self, key: str) -> list[float]:
        v = self.values.get(key)
        try:
            return [float(x) for x in v.split(",")] if v else []
        except ValueError:
            log.warning("Malformed float array for %r: %r", key, v)
            return []


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
    try:
        crc_ok = want == xor8(body.encode("ascii"))
    except UnicodeEncodeError:
        # Line noise decoded to U+FFFD by the frame reader — the body bytes are not
        # what the firmware sent, so the frame is corrupt regardless of the crc line.
        crc_ok = False

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
        host: str | None = None,
        tcp_port: int = 5555,
        connect_timeout: float = 2.0,
        byte_timeout: float = 0.25,
        command_timeout: float = 1.0,
        max_errors: int = 5,
        request_checksum: bool = False,
        transport=None,
    ):
        self.port = port
        self.baudrate = baudrate
        self.host = host
        self.tcp_port = tcp_port
        self.connect_timeout = connect_timeout
        self.byte_timeout = byte_timeout
        self.command_timeout = command_timeout
        self.max_errors = max_errors
        self.request_checksum = request_checksum

        self._ser = transport
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dro-link")

        self._connected = False
        self._error_count = 0
        self.error_total = 0                          # cumulative comm errors (for the Stats screen)
        self._last_error: str | None = None
        self._transport_broken = False                # set when the pipe itself failed (reopen)

    # ── transport selection ──────────────────────────────────────────
    @property
    def kind(self) -> str:
        """"tcp" when built for Ethernet (host given, even if blank), else "serial".

        The distinction is host is None (serial) vs host is a string (tcp) — a blank tcp host
        is a not-yet-configured board, which stays disconnected rather than falling back to serial.
        """
        return "tcp" if self.host is not None else "serial"

    @property
    def description(self) -> str:
        """Human-readable link target for logs / the status bar."""
        return f"tcp://{self.host}:{self.tcp_port}" if self.host is not None else str(self.port)

    # ── connection state (mirrors the old ConnectionManager semantics) ──
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def is_open(self) -> bool:
        """True once the underlying transport is open (independent of link health)."""
        return self._ser is not None

    def _mark_ok(self) -> None:
        if self._error_count:
            log.debug("Communication OK after %d error(s)", self._error_count)
        self._error_count = 0
        if not self._connected:
            self._connected = True
            self._last_error = None
            log.info("Communication restored with %s", self.description)

    def _mark_error(self, message: str) -> None:
        self._last_error = message
        self._error_count += 1
        self.error_total += 1
        if self._connected and self._error_count >= self.max_errors:
            self._connected = False
            log.warning(
                "Communication lost with %s after %d consecutive errors: %s",
                self.description, self._error_count, message,
            )

    # ── lifecycle ───────────────────────────────────────────────────
    async def open(self) -> None:
        if self._ser is not None:
            return
        loop = asyncio.get_running_loop()
        self._ser = await loop.run_in_executor(self._executor, self._open_transport)

    def _open_transport(self):
        """Build the byte pipe for the configured transport (runs on the executor thread)."""
        if self.kind == "tcp":
            if not self.host:
                # Ethernet selected but no board IP set yet — stay down until one is configured.
                raise ConnectionError("no board IP configured")
            from dro.comms.tcp_transport import TcpTransport
            return TcpTransport(self.host, self.tcp_port,
                                timeout=self.byte_timeout, connect_timeout=self.connect_timeout)
        return serial.Serial(self.port, self.baudrate, timeout=self.byte_timeout)

    async def _reset_transport(self) -> None:
        """Drop the current pipe (so :attr:`is_open` flips false and the poll loop reopens),
        keeping the executor alive. Used after a transport-level failure."""
        ser, self._ser = self._ser, None
        if ser is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(self._executor, self._safe_close, ser)

    @staticmethod
    def _safe_close(ser) -> None:
        try:
            ser.close()
        except Exception as e:  # noqa: BLE001 — closing must not raise upward
            log.debug("Error closing transport: %s", e)

    async def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            self._safe_close(ser)
        self._executor.shutdown(wait=False)

    # ── core transaction ─────────────────────────────────────────────
    async def command(self, text: str, *, timeout: float | None = None, retries: int = 3) -> Response:
        """Send a command line and return its parsed :class:`Response` (serialized on the bus)."""
        if self._ser is None:
            raise ProtocolError("client not open")
        if not text.isascii():
            raise ProtocolError(f"command is not ASCII: {text!r}")
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
        # A transport-level failure (closed socket / yanked cable) can't be fixed by retrying
        # on the same handle — drop it so is_open flips false and the poll loop reopens.
        if self._transport_broken:
            self._transport_broken = False
            await self._reset_transport()
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
            except (serial.SerialException, OSError) as e:
                # Serial cable yanked or TCP socket closed/reset — the pipe is dead, not just
                # a glitchy frame. Flag it so command() reopens after this transaction.
                self._last_error = str(e)
                self._transport_broken = True
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
        print("usage: python -m dro.comms.protocol_client <port|tcp://host[:port]> [command words...]")
        return 2
    target = argv[1]
    cmd = " ".join(argv[2:]) or "version"
    if target.startswith("tcp://"):
        hostport = target[len("tcp://"):]
        host, _, p = hostport.partition(":")
        client = ProtocolClient(host=host, tcp_port=int(p) if p else 5555)
    else:
        client = ProtocolClient(target)
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
