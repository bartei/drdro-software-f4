"""Firmware update orchestration over RS-485.

Drives the dual-bank update cycle (design: ../drdro-firmware-f4/dualbank_design.md,
ported from tools/dro_update.py):
  1. (app)  `update`        -> jump into the bootloader CLI ("bootloader=ready")
  2. (boot) `info`          -> pick the inactive bank (unless one is given)
  3. (boot) `flash <bank>`  -> YMODEM-send the .bin into that bank
  4. (boot) `bank <bank>`   -> select it as the active bank (persisted)
  5. (boot) `boot`          -> copy active bank -> Exec, jump to the new app

Available versions are fetched from the firmware repo's GitHub releases (the `drdro-app.bin`
asset). The flash flow takes exclusive ownership of the serial bus: the caller pauses the
board poll loop (Board.pause) and the whole sequence runs under the client's bus lock via
ProtocolClient.run_blocking. Progress/status are reported through callbacks (the UI wraps
them with @mainthread).
"""
from __future__ import annotations

import ssl
import time

import aiohttp
import certifi

from dro.comms.ymodem import ymodem_send

# Verify TLS against certifi's CA bundle — robust across platforms (notably NixOS, where
# Python doesn't pick up the system CA store automatically).
_SSL_CTX = ssl.create_default_context(cafile=certifi.where())

GITHUB_REPO = "bartei/drdro-firmware-f4"
APP_ASSET = "drdro-app.bin"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"


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
    def __init__(self, board):
        self.board = board
        self.client = board.connection

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
        async with aiohttp.ClientSession() as s:
            async with s.get(RELEASES_URL, ssl=_SSL_CTX,
                             headers={"Accept": "application/vnd.github+json"}) as r:
                r.raise_for_status()
                data = await r.json()
        out = []
        for rel in data:
            if rel.get("prerelease") and not include_prerelease:
                continue
            assets = rel.get("assets", [])
            asset = next((a for a in assets if a["name"] == APP_ASSET), None)
            if asset is None:
                asset = next((a for a in assets
                              if a["name"].endswith(".bin") and "app" in a["name"].lower()), None)
            if asset is None:
                continue
            out.append({
                "tag": rel["tag_name"],
                "name": rel.get("name") or rel["tag_name"],
                "prerelease": bool(rel.get("prerelease")),
                "url": asset["browser_download_url"],
                "size": asset["size"],
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
