from kivy.uix.widget import Widget

from dro.components.home.dro_coordbar import DroCoordBar
from dro.components.home.mode_layout import ModeLayout


class DroModeLayout(ModeLayout):
    """DRO mode: simplified DroCoordBars filling all space, no bottom bar."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Trailing spacer keeps the coordbars pinned to the TOP: it soaks up the space the bars
        # release when they hit their height cap, so the blank space sits below them rather than
        # pushing them down. Tiny size_hint_y → collapses to ~0 when the bars already fill.
        self.spacer = Widget(size_hint_y=0.0001)
        self.build_axis_bars()
        self.add_widget(self.spacer)

    def build_axis_bars(self):
        for axis_disp in self.app.axes:
            cb = DroCoordBar(axis=axis_disp)
            self.axis_bars.append(cb)
            self.add_widget(cb)

    def rebuild_axes(self):
        self.remove_widget(self.spacer)
        super().rebuild_axes()
        self.add_widget(self.spacer)
