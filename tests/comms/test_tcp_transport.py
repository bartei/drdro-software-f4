"""Unit tests for the TCP transport (v1.5 W5500 Ethernet path).

Exercised against a real loopback TCP server in a background thread — no hardware. Covers the
pyserial-compatible surface the client relies on: buffered ``read``, ``b""`` on timeout,
``ConnectionError`` on peer close, and Nagle disabled.
"""
import socket
import threading

import pytest

from dro.comms.tcp_transport import TcpTransport


def _serve_once(handler):
    """Loopback TCP server; run ``handler(conn)`` for the first client, then close. Returns (host, port, thread)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host, port = srv.getsockname()

    def run():
        try:
            conn, _ = srv.accept()
            try:
                handler(conn)
            finally:
                conn.close()
        finally:
            srv.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return host, port, t


def test_read_is_buffered_and_write_roundtrips():
    got = []

    def handler(conn):
        got.append(conn.recv(1024))
        conn.sendall(b"abc")
        conn.recv(1024)                 # block until the client closes

    host, port, t = _serve_once(handler)
    tr = TcpTransport(host, port, timeout=0.5)
    try:
        assert tr.write(b"hello\r") == 6
        # One recv on the wire feeds three per-byte read(1) calls from the buffer.
        assert tr.read(1) == b"a"
        assert tr.read(1) == b"b"
        assert tr.read(1) == b"c"
    finally:
        tr.close()
        t.join(timeout=1)
    assert got and got[0] == b"hello\r"


def test_read_timeout_returns_empty():
    def handler(conn):
        conn.recv(1024)                 # send nothing; hold open until client closes

    host, port, t = _serve_once(handler)
    tr = TcpTransport(host, port, timeout=0.1)
    try:
        assert tr.read(1) == b""        # nothing sent → timeout → b"" (pyserial parity)
    finally:
        tr.close()
        t.join(timeout=1)


def test_read_raises_connection_error_on_peer_close():
    def handler(conn):
        conn.sendall(b"x")              # then the wrapper closes the socket

    host, port, t = _serve_once(handler)
    tr = TcpTransport(host, port, timeout=0.5)
    try:
        assert tr.read(1) == b"x"       # in-order: data first…
        with pytest.raises(ConnectionError):
            tr.read(1)                  # …then EOF (recv b"") surfaces as ConnectionError
    finally:
        tr.close()
        t.join(timeout=1)


def test_nagle_disabled():
    def handler(conn):
        conn.recv(1024)

    host, port, t = _serve_once(handler)
    tr = TcpTransport(host, port, timeout=0.2)
    try:
        assert tr._sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == 1
    finally:
        tr.close()
        t.join(timeout=1)


def test_connect_refused_raises_oserror():
    # Bind+close to get a definitely-closed port, then connecting must raise (OSError family).
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(OSError):
        TcpTransport("127.0.0.1", port, connect_timeout=0.5)
