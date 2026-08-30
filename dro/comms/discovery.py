"""Local-network discovery for drDRO boards.

Sweeps the host's local IPv4 /24 subnet(s) for TCP listeners on the CLI port (default 5555),
sends a ``version`` request, and returns the ones that answer with a valid framed reply
(``key=value`` + ``crc=HH`` + blank line). Pure asyncio — a probe is one non-blocking
``open_connection`` guarded by a semaphore, so a full /24 (254 hosts) sweeps in ~1–2 s without
spawning threads. Runs on the app's existing asyncio loop.

Only the /24 around each local address is scanned (the common LAN case); a board on a different
subnet is reached by typing its IP on the Connection page instead.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket

from kivy.logger import Logger

from dro.comms.protocol_client import frame_request, parse_response

log = Logger.getChild(__name__)

DEFAULT_PORT = 5555


def _local_ipv4s() -> set[str]:
    """Best-effort set of this host's own IPv4 addresses (loopback/link-local excluded)."""
    ips: set[str] = set()
    # Primary outbound-interface address (connect on a UDP socket sends nothing on the wire).
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    # Anything the hostname resolves to (covers multi-homed hosts).
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    out: set[str] = set()
    for ip in ips:
        try:
            a = ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or a.is_unspecified:
            continue
        out.add(ip)
    return out


def local_scan_hosts() -> list[str]:
    """Host addresses to probe: the /24 around each local IPv4, minus our own addresses."""
    own = _local_ipv4s()
    hosts: list[str] = []
    seen: set[str] = set()
    for ip in own:
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        for h in net.hosts():
            hs = str(h)
            if hs in own or hs in seen:
                continue
            seen.add(hs)
            hosts.append(hs)
    return hosts


async def _read_frame(reader, deadline: float) -> list[str]:
    """Read framed ``key=value`` lines until the blank-line terminator (or the deadline)."""
    lines: list[str] = []
    seen = False
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(reader.readline(), remaining)
        except asyncio.TimeoutError:
            break
        if not raw:                       # EOF
            break
        line = raw.decode("ascii", "replace").replace("\r", "").strip()
        if line == "":
            if seen:
                break
            continue
        seen = True
        lines.append(line)
    return lines


async def probe(host: str, port: int = DEFAULT_PORT, *, timeout: float = 0.5) -> dict | None:
    """Connect + ``version``; return ``{host, port, version}`` on a valid reply, else ``None``."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        writer.write(frame_request("version"))
        await writer.drain()
        lines = await _read_frame(reader, deadline)
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 0.2)
        except (OSError, asyncio.TimeoutError):
            pass
    resp = parse_response(lines)
    if resp.crc_ok and resp.text("version"):
        return {"host": host, "port": port, "version": resp.text("version")}
    return None


async def discover(port: int = DEFAULT_PORT, *, timeout: float = 0.5, concurrency: int = 128,
                   on_progress=None) -> list[dict]:
    """Sweep the local subnet(s); return discovered boards sorted by address.

    ``on_progress(done, total, result_or_None)`` is called after each probe (same loop/thread).
    """
    hosts = local_scan_hosts()
    total = len(hosts)
    found: list[dict] = []
    done = 0
    sem = asyncio.Semaphore(concurrency)

    async def one(h: str):
        nonlocal done
        async with sem:
            r = await probe(h, port, timeout=timeout)
        done += 1
        if on_progress:
            on_progress(done, total, r)
        if r:
            found.append(r)
            log.info("Discovered drDRO board at %s:%d (%s)", r["host"], r["port"], r["version"])

    if total:
        await asyncio.gather(*(one(h) for h in hosts))
    found.sort(key=lambda d: tuple(int(x) for x in d["host"].split(".")))
    return found
