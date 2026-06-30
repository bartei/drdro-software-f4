"""RetroProgressBar — a dead-simple progress bar (Windows 3.1 style).

A solid-color fill proportional to (value - min) / (max - min), inside a 1px frame. No text,
no gradient, no animation. All visuals are a single canvas; colors and border width are
configurable. Drop-in replacement for kivy's ProgressBar (same min/max/value semantics).
"""
from kivy.properties import NumericProperty, ColorProperty, AliasProperty
from kivy.uix.widget import Widget

from dro.utils.kv_loader import load_kv

load_kv(__file__)


class RetroProgressBar(Widget):
    min = NumericProperty(0.0)
    max = NumericProperty(100.0)
    value = NumericProperty(0.0)

    fill_color = ColorProperty([1.0, 0.8, 0.2, 1])      # solid progress fill
    border_color = ColorProperty([0.5, 0.5, 0.5, 1])    # 1px frame
    background_color = ColorProperty([0, 0, 0, 1])      # well behind the fill
    border_width = NumericProperty(1)

    def _get_fraction(self):
        span = self.max - self.min
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.value - self.min) / float(span)))

    # 0..1, clamped; recomputed whenever min/max/value change (drives the fill width in KV).
    fraction = AliasProperty(_get_fraction, None, bind=("min", "max", "value"))
