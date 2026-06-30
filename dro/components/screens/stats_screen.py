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

    def set_ribbon(self, value):
        self.app.formats.show_stats_ribbon = bool(value)
