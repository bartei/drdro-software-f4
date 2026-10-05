"""Firmware update orchestration over RS-485.

Drives the dual-bank update cycle (design: ../drdro-firmware-f4/dualbank_design.md,
ported from tools/dro_update.py):
  1. (app)  `update`        -> jump into the bootloader CLI ("bootloader=ready")
  2. (boot) `info`          -> pick the inactive bank (unless one is given)
  3. (boot) `flash <bank>`  -> YMODEM-send the .bin into that bank
  4. (boot) `bank <bank>`   -> select it as the active bank (persisted)
  5. (boot) `boot`          -> copy active bank -> Exec, jump to the new app

Available versions are fetched from GitHub releases. **Which** repo and asset depends on the
board that is actually connected — see :class:`FirmwareSource` — so one Firmware screen serves
both the V1.5 mainboard and the older F411CE controller. The flash flow takes exclusive
ownership of the serial bus: the caller pauses the board poll loop (Board.pause) and the whole
sequence runs under the client's bus lock via ProtocolClient.run_blocking. Progress/status are
reported through callbacks (the UI wraps them with @mainthread).
"""
from __future__ import annotations

import ssl
import time
from dataclasses import dataclass

import aiohttp
import certifi

from dro.comms.ymodem import ymodem_send

# Verify TLS against certifi's CA bundle — robust across platforms (notably NixOS, where
# Python doesn't pick up the system CA store automatically).
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())


@dataclass(frozen=True)
class FirmwareSource:
    """Where a given board's firmware comes from.

    The two boards run different images from different repos, and pushing one to the other
    bricks it — the firmware projects deliberately give their release assets distinct names
    for exactly this reason ("this board's images must never be pushed to the old board by an
    updater matching on name", drdro-mainboard tools/build-release.sh). :meth:`matches` is the
    host side of that contract: it is the only thing that decides which asset gets flashed.
    """

    key: str                       # stable id, used in logs/tests
    label: str                     # shown on the Firmware screen
    repo: str                      # GitHub "owner/name"
    asset: str                     # exact release asset filename
    allow_loose: bool = False      # accept a differently-named app .bin (legacy releases)
    reject: tuple[str, ...] = ()   # substrings that disqualify an asset outright

    @property
    def releases_url(self) -> str:
        return f"https://api.github.com/repos/{self.repo}/releases"

    def matches(self, name: str) -> bool:
        """True when `name` is this board's application image.

        Exact name always. The loose form — any `.bin` describing itself as an app — exists
        only to keep releases that predate the current naming reachable, so it is opt-in per
        source and still refuses anything carrying another board's marker.
        """
        low = name.lower()
        if any(r in low for r in self.reject):
            return False
        if name == self.asset:
            return True
        return self.allow_loose and low.endswith(".bin") and "app" in low


# The V1.5 mainboard: STM32F411RET6, W5500 Ethernet, `net.*` in the protocol registry.
MAINBOARD_V15 = FirmwareSource(
    key="mainboard-v15",
    label="Mainboard V1.5",
    repo="bartei/drdro-mainboard",
    asset="drdro-mainboard-app.bin",
    # Every release of this board has carried the current asset name, so there is no legacy
    # naming to accommodate and no reason to accept anything but the exact file.
    allow_loose=False,
)

# The original controller: STM32F411CEU6, RS-485 only. Its assets are unprefixed, so the
# mainboard's images have to be excluded explicitly or the loose match would accept them.
LEGACY_F4 = FirmwareSource(
    key="f4",
    label="Controller (F411CE)",
    repo="bartei/drdro-firmware-f4",
    asset="drdro-app.bin",
    allow_loose=True,
    reject=("mainboard", "bootloader", "factory"),
)

FIRMWARE_SOURCES = (MAINBOARD_V15, LEGACY_F4)

# Protocol variable that exists only on the V1.5 mainboard. `net.*` is backed by the W5500,
# which the older board does not have at all, so this cannot be backported away — unlike a
# version number, which both boards have and which their release lines number independently.
BOARD_MARKER = "net.mac"


def detect_source(board) -> FirmwareSource:
    """Pick the firmware source for the connected board.

    Reads the `settings` snapshot the Board already caches on connect, so identifying the
    board costs no extra round trip. An unknown/offline board falls back to the legacy
    controller: that is the older, more widely deployed hardware, and its `reject` list means
    a wrong guess can still never offer a mainboard image.
    """
    try:
        marker = board.cached(BOARD_MARKER)
    except Exception:                       # noqa: BLE001 — detection must never break the UI
        marker = None
    # Presence, not value. The old board has no `net.*` registry at all, so the key is simply
    # absent from its settings dump and `cached` returns None; a V1.5 board always returns
    # *something*, but not necessarily something meaningful — a factory-flashed board reports
    # net.mac=00:00:00:00:00:00 until one is assigned. Testing truthiness would read a
    # degenerate value as "old board" and offer an image that cannot run on this hardware,
    # which is the one mistake this function must never make.
    return MAINBOARD_V15 if marker is not None else LEGACY_F4


def select_asset(assets: list[dict], source: FirmwareSource) -> dict | None:
    """Pick the application image for `source` out of one release's asset list.

    Exact filename wins; :meth:`FirmwareSource.matches` decides the rest and is what keeps
    another board's image from ever being selected.
    """
    return (next((a for a in assets if a.get("name") == source.asset), None)
            or next((a for a in assets if source.matches(a.get("name", ""))), None))


class UpdaterError(Exception):
    pass


# ---- raw framed helpers (operate on a pyserial port; run on the executor thread) ----
def _read_frame(ser, timeout=3.0) -> dict:
    """Read a framed key=value response (until a blank line). Returns a dict."""
    deadline = time.monotonic() + timeout
    buf = b""
    kv = {}
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
                    return kv
                continue
            seen = True
            if "=" in line:
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
        else:
            buf += c
    return kv


def _cli(ser, cmd, timeout=3.0, retries=3) -> dict:
    """Send a CLI command, returning the parsed framed response. Retries on an empty or
    'unknown command' reply (the RS485 turnaround can drop the first byte after a TX)."""
    resp = {}
    for _ in range(retries):
        ser.reset_input_buffer()
        ser.write((cmd + "\r").encode())
        ser.flush()
        resp = _read_frame(ser, timeout)
        if resp and resp.get("error") != "unknown command" and "error" not in resp:
            return resp
        time.sleep(0.15)
    if "error" in resp:
        raise UpdaterError(f"`{cmd}` -> error={resp['error']}")
    return resp


def _enter_bootloader(ser, status):
    status("Requesting update — entering bootloader…")
    ser.reset_input_buffer()
    ser.write(b"update\r")
    ser.flush()
    # Wait until we've seen "bootloader" AND the frame terminator (\n\n): the substring match
    # tolerates a glitched first greeting byte, and the terminator means the bootloader is
    # back in RX before we send a command.
    deadline = time.monotonic() + 8.0
    buf = b""
    while time.monotonic() < deadline:
        c = ser.read(1)
        if not c:
            continue
        buf += c
        if b"bootloader" in buf and buf.endswith(b"\n\n"):
            time.sleep(0.15)
            ser.reset_input_buffer()
            return
    raise UpdaterError("bootloader did not announce itself ('bootloader=ready')")


class FirmwareUpdater:
    def __init__(self, board, source: FirmwareSource | None = None):
        self.board = board
        self.client = board.connection
        # Resolved lazily: at construction the board may not have connected yet, so its
        # settings snapshot — where the marker lives — does not exist. Pass `source`
        # explicitly to pin it (tests, or a deliberate override).
        self._pinned = source
        self._source: FirmwareSource | None = source

    @property
    def source(self) -> FirmwareSource:
        """The connected board's firmware source, detected on first use and then cached."""
        if self._source is None:
            self._source = detect_source(self.board)
        return self._source

    def refresh_source(self) -> FirmwareSource:
        """Re-detect after a (re)connect — the board may be a different one entirely."""
        if self._pinned is None:
            self._source = None
        return self.source

    # ---- framed control commands (app CLI) ----
    async def get_version(self) -> str | None:
        return (await self.client.command("version")).text("version")

    async def get_active_bank(self) -> int | None:
        r = await self.client.command("bank")
        v = r.text("bank.active")
        return int(v) if v is not None else None

    async def set_active_bank(self, bank: int) -> bool:
        return bool(await self.client.command(f"bank {int(bank)}"))

    async def reset(self) -> None:
        """Ask the firmware to reboot (jumps via the bootloader into the active bank)."""
        self.board.pause()
        try:
            await self.client.command("reset")
        finally:
            time.sleep(0.1)
            self.board.resume()

    # ---- GitHub releases ----
    async def list_releases(self, include_prerelease: bool = False) -> list[dict]:
        """Releases from the connected board's own firmware repo, newest first."""
        src = self.source
        async with aiohttp.ClientSession() as s:
            async with s.get(src.releases_url, ssl=_SSL_CTX,
                             headers={"Accept": "application/vnd.github+json"}) as r:
                r.raise_for_status()
                data = await r.json()
        out = []
        for rel in data:
            if rel.get("prerelease") and not include_prerelease:
                continue
            asset = select_asset(rel.get("assets", []), src)
            if asset is None:
                continue
            out.append({
                "tag": rel["tag_name"],
                "name": rel.get("name") or rel["tag_name"],
                "prerelease": bool(rel.get("prerelease")),
                "url": asset["browser_download_url"],
                "size": asset["size"],
                "source": src.key,
                "asset": asset["name"],
            })
        return out

    async def download_asset(self, url: str, dest: str, on_progress=None) -> str:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, ssl=_SSL_CTX) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", 0))
                got = 0
                with open(dest, "wb") as f:
                    async for chunk in r.content.iter_chunked(8192):
                        f.write(chunk)
                        got += len(chunk)
                        if on_progress and total:
                            on_progress(got / total)
        return dest

    # ---- install (download already done; bin_path is local) ----
    async def install(self, bin_path: str, bank: int | None = None,
                       on_progress=None, on_status=None) -> dict:
        """Flash bin_path into a bank and boot it. Pauses the poll loop for exclusive bus use."""
        status = on_status or (lambda *_: None)
        progress = on_progress or (lambda *_: None)

        self.board.pause()
        time.sleep(0.2)                       # let any in-flight poll finish
        try:
            result = await self.client.run_blocking(
                lambda ser: self._flash_flow(ser, bin_path, bank, progress, status)
            )
        finally:
            self.board.resume()
        # Give the new app a moment, then read its version back through the resumed client.
        status("Verifying new firmware…")
        ver = None
        for _ in range(8):
            r = await self.client.command("version", retries=2)
            if r.text("version"):
                ver = r.text("version")
                break
        result["version"] = ver
        status(f"Done — running {ver}" if ver else "Flashed; version not confirmed yet")
        return result

    def _flash_flow(self, ser, bin_path, bank, progress, status) -> dict:
        """Synchronous flash cycle on the raw serial port (executor thread, bus lock held)."""
        _enter_bootloader(ser, status)

        if bank is None:
            info = _cli(ser, "info")
            active = int(info.get("bank.active", "0"))
            bank = 1 - active
            status(f"Active bank {active} → flashing inactive bank {bank}")
        else:
            status(f"Flashing bank {bank}")

        ser.reset_input_buffer()
        ser.write(f"flash {bank}\r".encode())
        ser.flush()
        sent = ymodem_send(ser, bin_path, on_progress=lambda s, t: progress(s / t if t else 0.0))
        res = _read_frame(ser, 5.0)
        if "error" in res or "flash" not in res:
            raise UpdaterError(f"flash failed: {res}")
        status(f"Bank {bank} written ({res.get('size', sent)} bytes, crc={res.get('crc', '?')})")

        _cli(ser, f"bank {bank}")
        status(f"Selected bank {bank} as active — booting…")
        ser.write(b"boot\r")                  # copies active bank -> Exec, jumps (no framed reply)
        ser.flush()
        time.sleep(2.0)
        return {"bank": bank, "size": res.get("size", sent), "crc": res.get("crc")}
