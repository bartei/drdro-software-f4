"""PositioningAid — G2 graphic positioning aid (near-zero / distance-to-go bar).

A centered horizontal indicator drawn under an axis' position. A hollow target dot sits
at the center (the nominal position). While the axis is off-target a solid bar grows from
the center toward the side the axis is offset to, its length proportional to the remaining
distance (clamped to ``span``). Within ``tolerance`` the dot fills solid to signal
"spot on" and the bar vanishes. All logic that produces ``value`` (distance-to-go) lives
in :class:`~dro.dispatchers.axis.AxisDispatcher`; this widget is a pure indicator plus a
tap/long-press affordance to set/clear the axis target.
"""
from kivy.clock import Clock
from kivy.properties import (
    AliasProperty,
    BooleanProperty,
    ColorProperty,
    NumericProperty,
    ObjectProperty,
)
from kivy.uix.widget import Widget

from dro.utils.kv_loader import load_kv

load_kv(__file__)

LONG_PRESS_THRESHOLD = 1.0
EDGE_PAD = 6  # px kept clear at each end so the bar never touches the widget border


class PositioningAid(Widget):
    axis = ObjectProperty(None, allownone=True)

    value = NumericProperty(0.0)        # signed distance-to-go, display units
    tolerance = NumericProperty(0.05)   # on-target threshold, display units
    span = NumericProperty(1.0)         # full-scale distance for the bar, display units
    active = BooleanProperty(False)     # a target is armed; idle aids stay quiet

    bar_color = ColorProperty([1.0, 0.8, 0.2, 1])
    at_target_color = ColorProperty([0.2, 1.0, 0.2, 1])
    dot_color = ColorProperty([1.0, 0.8, 0.2, 1])
    track_color = ColorProperty([0.3, 0.3, 0.3, 1])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._long_press_event = None

    # ── Derived geometry (drive the KV canvas) ───────────────────────
    def _get_at_target(self):
        return self.active and abs(self.value) <= self.tolerance

    at_target = AliasProperty(_get_at_target, None, bind=("value", "tolerance", "active"))

    def _get_fraction(self):
        if self.span <= 0:
            return 0.0
        return max(0.0, min(1.0, abs(self.value) / float(self.span)))

    fraction = AliasProperty(_get_fraction, None, bind=("value", "span"))

    def _get_direction(self):
        # 0 while on target so the bar collapses; +1 offset positive, -1 offset negative.
        if abs(self.value) <= self.tolerance:
            return 0
        return 1 if self.value > 0 else -1

    direction = AliasProperty(_get_direction, None, bind=("value", "tolerance"))

    def _get_dot_radius(self):
        return max(3.0, min(self.height * 0.3, 14.0))

    dot_radius = AliasProperty(_get_dot_radius, None, bind=("height",))

    def _get_bar_len(self):
        if self.direction == 0:
            return 0.0
        avail = max(0.0, self.width / 2.0 - EDGE_PAD - self.dot_radius)
        return self.fraction * avail

    bar_len = AliasProperty(
        _get_bar_len, None,
        bind=("fraction", "direction", "width", "dot_radius"),
    )

    # ── Touch: tap sets the target, long-press clears it ─────────────
    def on_touch_down(self, touch):
        if self.axis is None or not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        touch.grab(self)
        self._long_press_event = Clock.schedule_once(self._do_clear, LONG_PRESS_THRESHOLD)
        return True

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self._long_press_event is not None:
                self._long_press_event.cancel()
                self._long_press_event = None
                if self.axis is not None:
                    self.axis.enter_target()
            return True
        return super().on_touch_up(touch)

    def _do_clear(self, dt):
        self._long_press_event = None
        if self.axis is not None:
            self.axis.clear_target()
