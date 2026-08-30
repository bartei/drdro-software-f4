"""TCP transport for the drDRO line protocol (W5500 Ethernet, one client at a time).

The V1.5 mainboard serves the *same* line protocol over TCP (default port 5555) as over
RS-485 — identical `key=value`+`crc=HH` framing, `\\r`/`\\n` terminated (see firmware
`NetCli.c`). So the only thing that differs from the serial path is the byte pipe.

This class deliberately mimics the small slice of the :class:`serial.Serial` API that
:class:`dro.comms.protocol_client.ProtocolClient` uses (``read`` / ``write`` / ``flush`` /
``reset_input_buffer`` / ``close``), so it drops straight into the client's executor-thread
``_transact`` loop with no special-casing. All calls are blocking and run on the client's
single serial/transport executor thread, exactly like pyserial.

``read`` returns ``b""`` on a timeout (matching pyserial's ``timeout=`` behaviour) and raises
:class:`ConnectionError` (an ``OSError``) when the board closes the socket, so the client's
error handling treats a dropped TCP link the same way it treats a yanked serial cable.
"""
from __future__ import annotations

import socket

from kivy.logger import Logger

log = Logger.getChild(__name__)

DEFAULT_TCP_PORT = 5555


class TcpTransport:
    """Blocking TCP byte pipe with a pyserial-compatible surface.

    Reads are buffered: a single ``recv`` pulls whatever segment the board sent and the
    per-byte ``read(1)`` calls in the frame reader are then served from memory, so a full
    response costs one syscall rather than one per byte (matters at the higher Ethernet
    poll rates).
    """

    def __init__(self, host: str, port: int = DEFAULT_TCP_PORT, *,
                 timeout: float = 0.25, connect_timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._buf = b""
        # create_connection blocks up to connect_timeout; raises OSError on refuse/unreachable.
        self._sock = socket.create_connection((host, port), timeout=connect_timeout)
        self._sock.settimeout(timeout)
        # Small request/response at high rate — disable Nagle so each frame ships immediately.
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        log.info("TCP transport connected to %s:%d", host, port)

    # ── pyserial-compatible surface ─────────────────────────────────
    def read(self, size: int = 1) -> bytes:
        """Return up to ``size`` bytes; ``b""`` on timeout; raise on a closed socket."""
        while len(self._buf) < size:
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:                      # orderly close by the board
                raise ConnectionError(f"connection closed by {self.host}:{self.port}")
            self._buf += chunk
        if not self._buf:
            return b""
        out, self._buf = self._buf[:size], self._buf[size:]
        return out

    def write(self, data) -> int:
        self._sock.sendall(bytes(data))
        return len(data)

    def flush(self) -> None:
        # sendall already blocks until the OS accepts the bytes; nothing to flush.
        pass

    def reset_input_buffer(self) -> None:
        """Drop any buffered/queued bytes so the next response starts clean (pyserial parity)."""
        self._buf = b""
        self._sock.setblocking(False)
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:                  # peer closed — nothing left to drain
                    break
        except (BlockingIOError, socket.timeout):
            pass                               # nothing more queued — expected
        except OSError:
            pass                               # dead socket surfaces on the next read/write
        finally:
            self._sock.settimeout(self.timeout)

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError as e:
            log.debug("Error closing TCP transport: %s", e)
