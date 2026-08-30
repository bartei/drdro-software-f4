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

**The line is shared.** The firmware's CLI UART is not exclusively ours: other firmware
subsystems log asynchronously onto it (``ETH: link up``, ``DHCP: discovering (PHY ...)``,
``PHY: mode '100M full' -> ...``). Such a line can land *inside* a response frame. It is not
part of the body the firmware checksummed, so :func:`_read_frame` filters it out by shape
(a body line is always ``dotted.key=value``) and the CRC then validates on the first try —
what used to be a multi-second retry storm is now a filtered line and a log entry. Stray
lines are counted in :class:`LinkStats` so the condition stays visible.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import serial

log = logging.getLogger(__name__)

# Errors that are likely an RS-485 turnaround glitch (dropped byte) rather than a real answer.
_GLITCH_ERRORS = frozenset({"unknown command", "unknown variable"})

# A response body line is always `<key>=<value>` with an identifier key (optionally dotted,
# never containing a space). Firmware status chatter — "DHCP: discovering (PHY 'auto-neg
# all')..." — cannot match, which is exactly what makes it separable from a real frame.
_BODY_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*=")

# Dead time between retries of a failed transaction. What is being retried is a dropped byte
# on RS-485 turnaround, and the firmware is ready again immediately — this only has to let the
# transceiver settle. It stalls a bus that also carries the status poll, so it stays short.
_RETRY_BACKOFF = 0.02

# Minimum seconds between anomaly warnings *per category*. A stray-line storm (the firmware
# retrying DHCP every few seconds, say) must not turn logging into the bottleneck; suppressed
# occurrences are counted and reported with the next one that gets through.
_WARN_PERIOD = 5.0

# Rolling window of round-trip samples kept for the percentile report.
_RTT_WINDOW = 512


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
    stray: list[str] = field(default_factory=list)   # non-protocol lines seen while framing
    rtt: float = 0.0                                 # seconds, request write → frame complete

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


def parse_response(lines: list[str], stray: list[str] | None = None) -> Response:
    """Parse the lines of one frame (body lines incl. the trailing ``crc=HH`` line).

    ``stray`` is the non-protocol chatter :func:`_read_frame` filtered out while framing this
    response; it is carried on the result for logging and never affects the checksum.
    """
    stray = list(stray or ())
    if not lines or not lines[-1].startswith("crc="):
        # No terminating crc line → incomplete/garbled frame (timeout or glitch).
        values, error = _split_kv(lines)
        return Response(lines=lines, values=values, error=error, crc_ok=False, stray=stray)

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
    return Response(lines=lines, values=values, error=error, crc_ok=crc_ok, stray=stray)


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


def _read_frame(ser, timeout: float) -> tuple[list[str], list[str]]:
    """Read one framed response: body ``key=value`` lines until a blank line.

    Returns ``(body_lines, stray_lines)``. ``body_lines`` includes the trailing ``crc=HH``
    line. On timeout it returns whatever was collected (possibly empty/partial), which
    :func:`parse_response` flags as ``crc_ok=False``.

    Two things this does beyond splitting on newlines:

    * **Resynchronise.** The firmware logs asynchronously onto the same UART, so a line like
      ``DHCP: discovering (PHY 'auto-neg all')...`` can appear anywhere in the stream. It is
      not part of the body the firmware checksummed, so admitting it would break the CRC of an
      otherwise perfect frame. Lines that don't have the ``dotted.key=value`` shape of a body
      line are therefore split off into ``stray`` rather than corrupting the response. A stray
      line also does not count as "content", so one arriving before the reply can't let the
      blank line that follows it terminate an empty frame.
    * **Read in bursts.** One blocking ``read(1)`` to wait for the head of the burst, then a
      single ``read(in_waiting)`` to take everything the driver already has. A 117-byte ``sta``
      reply costs a couple of syscalls instead of 117 — at a 50 Hz poll that is the difference
      between ~5.8k and ~100 syscalls per second on the UART.
    """
    deadline = time.monotonic() + timeout
    buf = b""
    lines: list[str] = []
    stray: list[str] = []
    seen = False
    while time.monotonic() < deadline:
        chunk = ser.read(1)
        if not chunk:
            continue
        pending = getattr(ser, "in_waiting", 0)
        if pending:
            chunk += ser.read(pending)
        buf += chunk
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode("ascii", "replace").replace("\r", "").strip()
            if line == "":
                if seen:
                    return lines, stray
                continue          # leading blank/glitch before any content
            if not _BODY_LINE.match(line):
                stray.append(line)
                continue          # firmware chatter sharing the line — not ours to checksum
            seen = True
            lines.append(line)
    return lines, stray


def _fmt(value) -> str:
    """Format a Python value for a ``set`` argument."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


class ProtocolError(Exception):
    """Raised for client-side protocol/usage errors (not firmware ``error=`` replies)."""


class LinkStats:
    """Rolling health counters for the link, so a stutter leaves evidence behind.

    Everything here is written from the executor thread and read from the Kivy thread. The
    writes are individual attribute rebinds and a bounded ``deque`` append — both atomic under
    the GIL — so a reader can see a momentarily inconsistent *set* of counters but never a
    torn value. That is the right trade for diagnostics: no lock on the hot path.
    """

    def __init__(self, window: int = _RTT_WINDOW):
        self.commands = 0            # transactions attempted (a retry is not a new command)
        self.ok = 0                  # transactions that returned a CRC-valid frame
        self.crc_fail = 0            # a frame arrived but the checksum did not match
        self.timeouts = 0            # no frame at all within the command timeout
        self.glitch = 0              # CRC-valid `unknown command`/`unknown variable`
        self.retries = 0             # extra attempts spent across all transactions
        self.transport_errors = 0    # the pipe itself failed (cable/socket)
        self.stray_lines = 0         # non-protocol lines filtered out of frames
        self.last_stray: str | None = None
        self._rtts: deque[float] = deque(maxlen=window)

    def record_rtt(self, seconds: float) -> None:
        self._rtts.append(seconds)

    def reset(self) -> None:
        """Zero the counters — used when the link is reconfigured onto a new target."""
        self.__init__(window=self._rtts.maxlen)

    @property
    def rtt_ms(self) -> dict[str, float]:
        """min / p50 / p95 / max of the rolling round-trip window, in milliseconds."""
        if not self._rtts:
            return {"min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
        ordered = sorted(self._rtts)
        def pct(q: float) -> float:
            return ordered[min(len(ordered) - 1, int(len(ordered) * q))] * 1000.0
        return {"min": ordered[0] * 1000.0, "p50": pct(0.50),
                "p95": pct(0.95), "max": ordered[-1] * 1000.0}

    @property
    def failures(self) -> int:
        return self.crc_fail + self.timeouts + self.glitch + self.transport_errors

    def snapshot(self) -> dict:
        """Flat dict for the Stats screen and the periodic health line."""
        r = self.rtt_ms
        return {
            "commands": self.commands, "ok": self.ok, "failures": self.failures,
            "crc_fail": self.crc_fail, "timeouts": self.timeouts, "glitch": self.glitch,
            "retries": self.retries, "transport_errors": self.transport_errors,
            "stray_lines": self.stray_lines, "last_stray": self.last_stray,
            "rtt_min_ms": r["min"], "rtt_p50_ms": r["p50"],
            "rtt_p95_ms": r["p95"], "rtt_max_ms": r["max"],
        }

    def summary(self) -> str:
        """One-line health digest for the log."""
        r = self.rtt_ms
        return (
            f"cmds={self.commands} ok={self.ok} fail={self.failures} "
            f"(crc={self.crc_fail} timeout={self.timeouts} glitch={self.glitch} "
            f"transport={self.transport_errors}) retries={self.retries} "
            f"stray={self.stray_lines} "
            f"rtt_ms p50={r['p50']:.1f} p95={r['p95']:.1f} max={r['max']:.1f}"
        )


class _WarnGate:
    """Rate limiter for the per-transaction anomaly warnings.

    Comms faults arrive in bursts — the point of the log is to show that a burst happened and
    what it looked like, not to print a line per poll at 50 Hz. Occurrences suppressed between
    two emissions are counted and reported with the next one that gets through.
    """

    def __init__(self, period: float = _WARN_PERIOD):
        self.period = period
        self._last: dict[str, float] = {}
        self._held: dict[str, int] = {}

    def allow(self, category: str) -> int | None:
        """Return the number of suppressed occurrences to report, or None to stay quiet."""
        now = time.monotonic()
        last = self._last.get(category)
        if last is not None and now - last < self.period:
            self._held[category] = self._held.get(category, 0) + 1
            return None
        self._last[category] = now
        return self._held.pop(category, 0)


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

        # Link instrumentation: counters + rolling round-trip window, plus the gate that keeps
        # a fault burst from flooding the log. Read by Board for the periodic health line and
        # by the Stats screen.
        self.stats = LinkStats()
        self._warn = _WarnGate()

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
            # Worth INFO rather than DEBUG once it is more than a single dropped frame: this
            # is the line that dates a stutter and says how long the link was unhappy.
            emit = log.info if self._error_count > 1 else log.debug
            emit("Link recovered after %d consecutive error(s) on %s — last was %s",
                 self._error_count, self.description, self._last_error)
        self._error_count = 0
        if not self._connected:
            self._connected = True
            self._last_error = None
            log.info("Communication restored with %s | %s", self.description, self.stats.summary())

    def _mark_error(self, message: str) -> None:
        self._last_error = message
        self._error_count += 1
        self.error_total += 1
        if self._connected and self._error_count >= self.max_errors:
            self._connected = False
            log.warning(
                "Communication lost with %s after %d consecutive errors: %s | %s",
                self.description, self._error_count, message, self.stats.summary(),
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
        attempts = max(1, retries)
        self.stats.commands += 1
        for attempt in range(attempts):
            if attempt:
                self.stats.retries += 1
            t0 = time.monotonic()
            try:
                self._ser.reset_input_buffer()
                self._ser.write(frame_request(text, self.request_checksum))
                self._ser.flush()
                lines, stray = _read_frame(self._ser, timeout)
            except (serial.SerialException, OSError) as e:
                # Serial cable yanked or TCP socket closed/reset — the pipe is dead, not just
                # a glitchy frame. Flag it so command() reopens after this transaction.
                self._last_error = str(e)
                self._transport_broken = True
                self.stats.transport_errors += 1
                log.error("Link down: transport failure on %s during %r — %s",
                          self.description, text, e)
                last = Response()
                break

            rtt = time.monotonic() - t0
            self.stats.record_rtt(rtt)
            if stray:
                self.stats.stray_lines += len(stray)
                self.stats.last_stray = stray[-1]
                self._log_stray(text, stray)

            resp = parse_response(lines, stray)
            resp.rtt = rtt
            last = resp
            if resp.crc_ok and resp.error not in _GLITCH_ERRORS:
                self.stats.ok += 1
                return resp

            # CRC/framing failure or a likely turnaround-glitch error → retry (if any left).
            if resp.crc_ok:
                self.stats.glitch += 1
                reason = f"glitch {resp.error!r}"
            elif not lines:
                self.stats.timeouts += 1
                reason = f"no reply within {timeout * 1000:.0f} ms"
            else:
                self.stats.crc_fail += 1
                reason = "crc/framing fail"
            self._last_error = f"{reason} (attempt {attempt + 1}/{attempts})"
            self._log_bad_frame(text, reason, attempt, attempts, lines, rtt)
            # Only back off if another attempt is actually going to happen — sleeping after
            # the final attempt is pure dead time on a bus the status poll is waiting for.
            if attempt + 1 < attempts:
                time.sleep(_RETRY_BACKOFF)
        return last

    # ── diagnostics (executor thread; rate-limited so a burst can't flood) ──
    def _log_stray(self, text: str, stray: list[str]) -> None:
        held = self._warn.allow("stray")
        if held is None:
            return
        log.warning(
            "Link chatter: unsolicited firmware output on %s during %r, filtered out of the "
            "frame — %s%s",
            self.description, text, " | ".join(repr(s) for s in stray[:3]),
            f" (+{held} more since the last report)" if held else "",
        )

    def _log_bad_frame(self, text: str, reason: str, attempt: int, attempts: int,
                       lines: list[str], rtt: float) -> None:
        held = self._warn.allow("badframe")
        if held is None:
            return
        log.warning(
            "Link fault: %s on %s to %r after %.1f ms (attempt %d/%d) — got %s%s",
            reason, self.description, text, rtt * 1000.0, attempt + 1, attempts,
            " | ".join(repr(l) for l in lines[:4]) if lines else "nothing",
            f" (+{held} more since the last report)" if held else "",
        )

    # ── convenience commands ─────────────────────────────────────────
    async def get(self, name: str) -> Response:
        return await self.command(f"get {name}")

    async def set(self, name: str, value, idx: int | None = None) -> Response:
        v = _fmt(value)
        text = f"set {name} {idx} {v}" if idx is not None else f"set {name} {v}"
        return await self.command(text)

    async def sta(self, *, timeout: float = 0.25, retries: int = 1) -> Response:
        """Status poll — deliberately *not* retried, and on a short leash.

        `sta` is issued continuously (50 Hz on RS-485, 100 Hz on Ethernet). Retrying one is
        pointless: the next poll is already the retry, and it carries fresher data. Worse, a
        retry holds the bus lock, so three attempts at the old 0.5 s timeout could freeze the
        readout — and every UI write queued behind it — for the better part of two seconds.
        That was the stutter. One attempt on a 0.25 s leash caps a lost poll at ~12 periods,
        and a measured round trip is ~14 ms, so the leash is still ~17x the p95.
        """
        return await self.command("sta", timeout=timeout, retries=retries)

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
