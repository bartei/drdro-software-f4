from kivy.uix.widget import Widget

from dro.components.home.coordbar import CoordBar
from dro.components.home.mode_layout import ModeLayout
from dro.components.home.servobar import ServoBar


class IndexModeLayout(ModeLayout):
    """Index mode: full CoordBars (with sync ratio Num/Den) + ServoBar."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.servo_bar = ServoBar()
        # Child order (top→bottom): coordbars, spacer, servobar. The spacer absorbs the space
        # the coordbars give up once they hit their height cap, so the bars stay pinned at the
        # TOP and the blank space lands between them and the servobar (instead of above them).
        # Its tiny size_hint_y means it only grows when the bars are capped — with enough bars
        # to fill, it collapses to ~0 and the layout is unchanged.
        self.spacer = Widget(size_hint_y=0.0001)
        self.build_axis_bars()
        self.add_widget(self.spacer)
        self.add_widget(self.servo_bar)

    def build_axis_bars(self):
        for axis_disp in self.app.axes:
            cb = CoordBar(axis=axis_disp)
            self.axis_bars.append(cb)
            self.add_widget(cb)

    def rebuild_axes(self):
        self.remove_widget(self.servo_bar)
        self.remove_widget(self.spacer)
        super().rebuild_axes()
        self.add_widget(self.spacer)
        self.add_widget(self.servo_bar)
