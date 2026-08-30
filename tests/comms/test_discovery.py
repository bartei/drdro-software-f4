"""Unit tests for local-network board discovery (v1.5).

``local_scan_hosts`` is tested with an injected local-IP set; ``probe``/``discover`` run against
a loopback asyncio server that frames a ``version`` reply exactly like the firmware — no hardware.
"""
import asyncio

from dro.comms import discovery
from dro.comms.protocol_client import xor8


def _run(coro):
    return asyncio.run(coro)


def _frame(body_lines: list[str]) -> bytes:
    """key=value lines + crc=HH + blank-line terminator, with a correct XOR-8 crc."""
    body = "".join(l + "\n" for l in body_lines)
    return (body + f"crc={xor8(body.encode()):02X}\n\n").encode("ascii")


def _make_handler(reply: bytes | None):
    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r")          # the client's `version\r` request
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        if reply is not None:
            writer.write(reply)
            await writer.drain()
        writer.close()
    return handle


# ── local_scan_hosts ─────────────────────────────────────────────────
def test_local_scan_hosts_excludes_own(monkeypatch):
    monkeypatch.setattr(discovery, "_local_ipv4s", lambda: {"192.168.1.50"})
    hosts = discovery.local_scan_hosts()
    assert "192.168.1.50" not in hosts          # our own address is skipped
    assert "192.168.1.1" in hosts and "192.168.1.254" in hosts
    assert len(hosts) == 253                     # /24 usable hosts (254) minus ourselves


def test_local_scan_hosts_empty_when_no_local_ip(monkeypatch):
    monkeypatch.setattr(discovery, "_local_ipv4s", lambda: set())
    assert discovery.local_scan_hosts() == []


# ── probe ────────────────────────────────────────────────────────────
def test_probe_returns_board_on_valid_reply():
    async def go():
        server = await asyncio.start_server(
            _make_handler(_frame(["version=v1.5.0-test"])), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await discovery.probe("127.0.0.1", port, timeout=1.0)

    r = _run(go())
    assert r == {"host": "127.0.0.1", "port": r["port"], "version": "v1.5.0-test"}


def test_probe_returns_none_on_garbage():
    async def go():
        # No crc line → parse_response flags crc_ok False → not a board.
        server = await asyncio.start_server(
            _make_handler(b"nope\n\n"), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            return await discovery.probe("127.0.0.1", port, timeout=1.0)

    assert _run(go()) is None


def test_probe_returns_none_on_no_listener():
    async def go():
        # Closed port: connection refused → None (not an exception).
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return await discovery.probe("127.0.0.1", port, timeout=0.5)

    assert _run(go()) is None


# ── discover ─────────────────────────────────────────────────────────
def test_discover_finds_server_and_reports_progress(monkeypatch):
    async def go():
        server = await asyncio.start_server(
            _make_handler(_frame(["version=v1.5.0-test"])), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(discovery, "local_scan_hosts", lambda: ["127.0.0.1"])
        progress = []
        async with server:
            found = await discovery.discover(
                port=port, timeout=1.0, on_progress=lambda d, t, r: progress.append((d, t)))
        return found, progress

    found, progress = _run(go())
    assert len(found) == 1 and found[0]["version"] == "v1.5.0-test"
    assert progress == [(1, 1)]                  # one probe, reported done
