"""Firmware screen — view/select banks, reboot the board, and flash a firmware version
fetched from GitHub releases over the RS-485 line (YMODEM into the inactive bank, then boot).
"""
import asyncio
import os
import tempfile

from kivy.clock import mainthread
from kivy.logger import Logger
from kivy.properties import BooleanProperty, NumericProperty, StringProperty, ListProperty
from kivy.uix.screenmanager import Screen

from dro.comms.updater import FirmwareUpdater
from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class FirmwareScreen(Screen):
    current_version = StringProperty("—")
    active_bank_text = StringProperty("—")
    boot_bank = StringProperty("")
    include_prerelease = BooleanProperty(False)
    version_options = ListProperty()
    selected_tag = StringProperty("")
    progress = NumericProperty(0.0)
    busy = BooleanProperty(False)
    status_text = StringProperty("")

    def __init__(self, **kv):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        super().__init__(**kv)
        self._releases: list[dict] = []
        self._updater: FirmwareUpdater | None = None

    @property
    def updater(self) -> FirmwareUpdater:
        if self._updater is None:
            self._updater = FirmwareUpdater(self.app.board)
        return self._updater

    # ── status helpers (safe from any thread) ───────────────────────
    @mainthread
    def _status(self, msg: str):
        log.info("firmware: %s", msg)
        self.status_text = (self.status_text + msg + "\n")[-4000:]

    @mainthread
    def _set_progress(self, frac: float):
        self.progress = max(0.0, min(1.0, float(frac)))

    def _spawn(self, coro):
        try:
            asyncio.get_event_loop().create_task(coro)
        except RuntimeError:
            log.error("no running asyncio loop for firmware task")
            coro.close()

    # ── lifecycle ────────────────────────────────────────────────────
    def on_pre_enter(self, *args):
        self.refresh_status()

    def refresh_status(self):
        self._spawn(self._refresh_status())

    async def _refresh_status(self):
        if not self.app.board.connected:
            self.current_version = "(offline)"
            self.active_bank_text = "—"
            return
        ver = await self.updater.get_version()
        bank = await self.updater.get_active_bank()
        self.current_version = ver or "—"
        self.active_bank_text = "—" if bank is None else str(bank)
        if bank is not None:
            self.boot_bank = str(bank)

    # ── bank selector / reset ────────────────────────────────────────
    def set_bank(self, value: str):
        if value not in ("0", "1"):
            return
        self.boot_bank = value                       # reflect the selection immediately
        if value != self.active_bank_text:
            self._spawn(self._set_bank(int(value)))

    async def _set_bank(self, bank: int):
        self._status(f"Setting active bank → {bank}")
        ok = await self.updater.set_active_bank(bank)
        self._status("Bank set (effective next boot)" if ok else "Bank set failed")
        await self._refresh_status()

    def do_reset(self):
        self._status("Rebooting firmware…")
        self._spawn(self._reset())

    async def _reset(self):
        await self.updater.reset()
        await asyncio.sleep(2.5)
        await self._refresh_status()
        self._status("Firmware rebooted")

    # ── releases ─────────────────────────────────────────────────────
    def refresh_releases(self):
        self._status("Fetching releases from GitHub…")
        self._spawn(self._refresh_releases())

    async def _refresh_releases(self):
        try:
            rels = await self.updater.list_releases(include_prerelease=self.include_prerelease)
        except Exception as e:                       # noqa: BLE001 — surface any network/parse error
            self._status(f"Failed to fetch releases: {e}")
            return
        self._releases = rels
        self.version_options = [r["tag"] for r in rels]
        self._status(f"Found {len(rels)} release(s)")
        if rels and not self.selected_tag:
            self.selected_tag = rels[0]["tag"]

    def select_version(self, tag: str):
        self.selected_tag = tag

    # ── install ──────────────────────────────────────────────────────
    def install_selected(self):
        if self.busy:
            return
        rel = next((r for r in self._releases if r["tag"] == self.selected_tag), None)
        if rel is None:
            self._status("Select a version first (Refresh versions)")
            return
        self._spawn(self._install(rel))

    async def _install(self, rel: dict):
        self.busy = True
        self._set_progress(0.0)
        try:
            self._status(f"Downloading {rel['tag']} ({rel['size']} bytes)…")
            tmp = os.path.join(tempfile.gettempdir(), f"drdro-{rel['tag']}.bin")
            await self.updater.download_asset(rel["url"], tmp, on_progress=self._set_progress)
            self._set_progress(0.0)
            self._status("Flashing over RS-485…")
            res = await self.updater.install(
                tmp, on_progress=self._set_progress, on_status=self._status,
            )
            self._set_progress(1.0)
            # The poll loop reconnects a moment after boot; wait for it, then refresh.
            for _ in range(15):
                if self.app.board.connected:
                    break
                await asyncio.sleep(0.3)
            await self._refresh_status()
            self._status(f"Update complete (bank {res.get('bank')}, version {res.get('version')})")
        except Exception as e:                        # noqa: BLE001 — report any failure to the UI
            log.exception("firmware update failed")
            self._status(f"Update FAILED: {e}")
        finally:
            self.busy = False
