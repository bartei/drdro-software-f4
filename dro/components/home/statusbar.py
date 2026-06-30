from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout

from dro.utils.kv_loader import load_kv

log = Logger.getChild(__name__)
load_kv(__file__)


class StatusBar(BoxLayout):
    update_tick = NumericProperty(0)
    comm_rate = NumericProperty(0)   # measured sta poll rate (Hz)
    cycles = NumericProperty(0)
    fps = NumericProperty(0)

    def __init__(self, **kv):
        from dro.app import MainApp
        self.app: MainApp = MainApp.get_running_app()
        self._ev = None
        super().__init__(**kv)

    def on_parent(self, instance, parent):
        # Only tick while actually mounted — a hidden ribbon does no work.
        if parent is not None and self._ev is None:
            self._ev = Clock.schedule_interval(self.update, 1.0 / 5)
        elif parent is None and self._ev is not None:
            self._ev.cancel()
            self._ev = None

    def update(self, *args, **kv):
        self.fps = Clock.get_fps()
        self.comm_rate = self.app.board.comm_rate
        self.cycles = self.app.board.diag_cycles
