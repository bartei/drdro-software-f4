"""Stats for nerds — live diagnostics: refresh rates, comm errors, firmware/software
versions. While this screen is open it enables the board's diag polling; on leave it stops,
so a normal session does no extra round-trips (unless the top ribbon is enabled here)."""
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.screenmanager import Screen

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class StatsScreen(Screen):
    sw_version = StringProperty("—")
    fw_version = StringProperty("—")
    connected = StringProperty("—")
    comm_rate = StringProperty("—")
    fps = StringProperty("—")
    board_rate = StringProperty("—")
    cycles = StringProperty("—")
    errors = StringProperty("—")
    rtt = StringProperty("—")
    failures = StringProperty("—")
    stray = StringProperty("—")
    last_stray = StringProperty("—")
    show_ribbon = BooleanProperty(False)

    def __init__(self, **kv):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        self._ev = None
        super().__init__(**kv)

    def on_pre_enter(self, *args):
        self.show_ribbon = self.app.formats.show_stats_ribbon
        self.app.board.stats_active = True       # enable diag.* polling while visible
        self.refresh()
        if self._ev is None:
            self._ev = Clock.schedule_interval(self.refresh, 0.25)

    def on_leave(self, *args):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self.app.board.stats_active = False      # stop diag polling when we leave

    def refresh(self, *args):
        b = self.app.board
        self.sw_version = self.app.version or "—"
        self.fw_version = b.firmware_version or "—"
        self.connected = "connected" if b.connected else "offline"
        self.comm_rate = f"{b.comm_rate:.0f} Hz"
        self.fps = f"{Clock.get_fps():.0f}"
        self.errors = str(getattr(b.connection, "error_total", 0))
        self.board_rate = f"{100000000 / b.diag_interval:.0f} Hz" if b.diag_interval else "—"
        self.cycles = str(b.diag_cycles) if b.diag_interval else "—"

        # Link health. `stray` counts unsolicited firmware log lines seen on the protocol line
        # (ETH/DHCP/PHY chatter); they are filtered out of frames rather than corrupting them,
        # but a climbing count is the visible symptom of the board talking over itself.
        ls = b.link_stats()
        self.rtt = (f"{ls['rtt_p50_ms']:.0f} / {ls['rtt_p95_ms']:.0f} / {ls['rtt_max_ms']:.0f} ms"
                    if ls.get("commands") else "—")
        self.stray = str(ls.get("stray_lines", 0))
        # These two render into output boxes rather than a fixed-width button, so they can
        # afford the full breakdown — and the stray line is reproduced verbatim, which is the
        # whole point of showing it (it names which firmware subsystem talked over the reply).
        if ls.get("commands"):
            self.failures = (
                f"{ls.get('failures', 0)} failed of {ls['commands']} commands, "
                f"{ls.get('retries', 0)} retries\n"
                f"crc {ls.get('crc_fail', 0)}   timeout {ls.get('timeouts', 0)}   "
                f"glitch {ls.get('glitch', 0)}   transport {ls.get('transport_errors', 0)}"
            )
        else:
            self.failures = "—"
        self.last_stray = ls.get("last_stray") or "—"

    def set_ribbon(self, value):
        self.app.formats.show_stats_ribbon = bool(value)
