"""Connection setup page — choose how the app reaches the board (RS-485 or Ethernet/TCP).

Persists to the same `config.ini` `[device]` section that `MainApp.build()` reads
(transport / host / tcp_port / serial_port / baudrate / refresh_hz), and applies changes live
via `Board.reconfigure()` + `Board.set_poll_period()` so no app restart is needed.

"Scan Network" sweeps the local subnet for boards listening on the CLI port and fills the
picker; selecting one sets the transport to TCP and fills in its IP (see `dro.comms.discovery`).

Defaults to RS-485 serial so an existing v1.0 install (no `transport` key) keeps its serial
link; the v1.5 board's Ethernet/TCP link is opt-in from this page.
"""
import asyncio

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import StringProperty, NumericProperty, ListProperty, BooleanProperty
from kivy.uix.screenmanager import Screen

from dro.components.appsettings import config
from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)

TRANSPORTS = ["tcp", "serial"]


class ConnectionScreen(Screen):
    transport = StringProperty("serial")
    host = StringProperty("")
    tcp_port = NumericProperty(5555)
    serial_port = StringProperty("/dev/serial0")
    baudrate = NumericProperty(115200)
    refresh_hz = NumericProperty(50)
    status_text = StringProperty("")

    discovered = ListProperty([])       # display strings: "ip  (version)"
    scanning = BooleanProperty(False)

    def __init__(self, **kv):
        super().__init__(**kv)
        from dro.app import MainApp
        self.app = MainApp.get_running_app()
        self._results = []              # discovered device dicts, parallel to `discovered`
        self._load_from_config()

    def _load_from_config(self):
        self.transport = config.getdefault("device", "transport", "serial")
        self.host = config.getdefault("device", "host", "")
        self.tcp_port = int(config.getdefault("device", "tcp_port", 5555))
        self.serial_port = config.getdefault("device", "serial_port", "/dev/serial0")
        self.baudrate = int(config.getdefault("device", "baudrate", 115200))
        self.refresh_hz = int(config.getdefault(
            "device", "refresh_hz", 100 if self.transport == "tcp" else 50))

    def on_pre_enter(self, *args):
        self._load_from_config()
        dd = self.ids.get("transport_dd")
        if dd is not None:
            dd.options = TRANSPORTS
            dd.value = self.transport

    def on_transport_selected(self, value: str):
        if value in TRANSPORTS:
            self.transport = value

    # ── network discovery ───────────────────────────────────────────
    def start_scan(self):
        """Kick off a subnet sweep for boards on the CLI port (async, non-blocking)."""
        if self.scanning:
            return
        Clock.schedule_once(lambda dt: asyncio.ensure_future(self.scan()))

    async def scan(self):
        from dro.comms import discovery
        self.scanning = True
        self.discovered = []
        self._results = []
        port = int(self.tcp_port) or discovery.DEFAULT_PORT
        self.status_text = f"Scanning the local network for boards on port {port}…"
        try:
            results = await discovery.discover(port=port, on_progress=self._scan_progress)
        except OSError as e:
            self.status_text = f"Scan failed: {e}"
            self.scanning = False
            return
        self._results = results
        self.discovered = [f"{r['host']}  ({r['version']})" for r in results]
        dd = self.ids.get("devices_dd")
        if dd is not None:
            dd.options = self.discovered or ["(none found)"]
        self.status_text = (f"Found {len(results)} board(s) — pick one below."
                            if results else "No boards found on the local subnet.")
        self.scanning = False

    def _scan_progress(self, done, total, result):
        # Runs on the same loop/thread — cheap Kivy property writes, throttled for the misses.
        if result:
            self.status_text = f"Scanning… {done}/{total} (found {result['host']})"
        elif done % 32 == 0 or done == total:
            self.status_text = f"Scanning… {done}/{total}"

    def on_device_selected(self, value: str):
        for r in self._results:
            if value.startswith(r["host"]):
                self.transport = "tcp"
                self.host = r["host"]
                self.tcp_port = r["port"]
                dd = self.ids.get("transport_dd")
                if dd is not None:
                    dd.value = "tcp"
                self.status_text = f"Selected {r['host']} ({r['version']}) — press Apply to connect."
                break

    def _save_to_config(self):
        if not config.has_section("device"):
            config.add_section("device")
        config.set("device", "transport", self.transport)
        config.set("device", "host", self.host)
        config.set("device", "tcp_port", str(int(self.tcp_port)))
        config.set("device", "serial_port", self.serial_port)
        config.set("device", "baudrate", str(int(self.baudrate)))
        config.set("device", "refresh_hz", str(int(self.refresh_hz)))
        config.write()

    def apply(self):
        """Persist the settings and rebuild the live link + poll rate."""
        self._save_to_config()
        board = self.app.board
        board.reconfigure(
            transport=self.transport,
            port=self.serial_port, baudrate=int(self.baudrate),
            host=self.host, tcp_port=int(self.tcp_port),
        )
        board.set_poll_period(1.0 / max(1.0, float(self.refresh_hz)))
        target = (f"tcp://{self.host}:{int(self.tcp_port)}" if self.transport == "tcp"
                  else f"{self.serial_port} @ {int(self.baudrate)}")
        if self.transport == "tcp" and not self.host:
            self.status_text = "TCP selected but no board IP set — enter one and Apply again."
        else:
            self.status_text = f"Applied — connecting to {target} ({int(self.refresh_hz)} Hz)…"
        log.info("Connection applied: %s", self.status_text)
