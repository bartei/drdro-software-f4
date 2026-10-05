"""ELS feed direction (thread hand) reverses the sign of the sync ratio.

Left-hand selection must reach the spindle axis as a negative numerator with a positive
denominator — that is the shape the firmware wants, since `scales.den` is used as a plain
divisor. Drives the real ElsBar methods on a duck-typed self (the widget's __init__ needs
a live app), same approach as test_els_custom_feed.
"""
from dro import feeds
from dro.components.home.elsbar import ElsBar


class _Axis:
    def __init__(self):
        self.syncRatioNum = None
        self.syncRatioDen = None


class _Board:
    def __init__(self, axis):
        self._axis = axis

    def get_spindle_axis(self):
        return self._axis


class _Servo:
    def __init__(self, servo_enable=0):
        self.servoEnable = servo_enable


class _App:
    def __init__(self, axis, servo_enable=0):
        self.board = _Board(axis)
        self.servo = _Servo(servo_enable)


class _FakeElsBar:
    """Stand-in for ElsBar, borrowing the real implementations under test."""
    direction_sign = ElsBar.direction_sign
    _push_feed_ratio = ElsBar._push_feed_ratio
    _reapply_feed_ratio = ElsBar._reapply_feed_ratio
    set_feed_direction = ElsBar.set_feed_direction
    toggle_feed_direction = ElsBar.toggle_feed_direction
    set_custom_feed = ElsBar.set_custom_feed
    update_feeds_ratio = ElsBar.update_feeds_ratio

    def __init__(self, axis, servo_enable=0, direction=1, table="Thread MM", index=0):
        self.app = _App(axis, servo_enable)
        self.mode_name = table
        self.current_feeds_table = feeds.table[table]
        self.current_feeds_index = index
        self.feed_name = ":("
        self.feed_direction = direction
        self._feed_ratio = None


# ── sign applied to table feeds ──────────────────────────────────────

def test_right_hand_pushes_positive_ratio():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=1, index=6)      # Thread MM "1.00" -> 1/1

    bar.update_feeds_ratio(bar, None)

    assert axis.syncRatioNum == 1
    assert axis.syncRatioDen == 1
    assert bar.feed_name == "1.00"


def test_left_hand_negates_the_numerator_only():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=-1, index=7)     # Thread MM "1.25" -> 5/4

    bar.update_feeds_ratio(bar, None)

    assert axis.syncRatioNum == -5
    assert axis.syncRatioDen == 4                      # denominator stays positive


def test_left_hand_on_imperial_thread():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=-1, table="Thread IN", index=0)   # 64 TPI -> 254/640

    bar.update_feeds_ratio(bar, None)

    assert axis.syncRatioNum < 0
    assert axis.syncRatioDen > 0
    # Magnitude is untouched by the hand.
    assert abs(axis.syncRatioNum) / axis.syncRatioDen == 254 / 640


# ── direction flips ──────────────────────────────────────────────────

def test_toggle_flips_sign_and_keeps_magnitude():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=1, index=7)      # 5/4
    bar.update_feeds_ratio(bar, None)
    assert (axis.syncRatioNum, axis.syncRatioDen) == (5, 4)

    bar.toggle_feed_direction()
    bar._reapply_feed_ratio()                          # Kivy binding fires this for real

    assert (axis.syncRatioNum, axis.syncRatioDen) == (-5, 4)


def test_flip_preserves_a_custom_feed():
    """Regression: the flip must re-push the custom ratio, not the table entry."""
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=1, index=0)
    feed = feeds.custom_feed("Thread MM", 1.3)         # 13/10, not in the table

    bar.set_custom_feed("Thread MM", feed)
    assert (axis.syncRatioNum, axis.syncRatioDen) == (13, 10)

    bar.toggle_feed_direction()
    bar._reapply_feed_ratio()

    assert (axis.syncRatioNum, axis.syncRatioDen) == (-13, 10)
    assert bar.feed_name == "1.3"                      # still the custom feed


def test_custom_feed_picks_up_the_active_hand():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=-1)
    feed = feeds.custom_feed("Thread MM", 1.3)

    bar.set_custom_feed("Thread MM", feed)

    assert (axis.syncRatioNum, axis.syncRatioDen) == (-13, 10)


def test_toggle_is_idempotent_over_two_flips():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=1, index=7)
    bar.update_feeds_ratio(bar, None)

    bar.toggle_feed_direction()
    bar._reapply_feed_ratio()
    bar.toggle_feed_direction()
    bar._reapply_feed_ratio()

    assert (axis.syncRatioNum, axis.syncRatioDen) == (5, 4)


# ── servo interlock ──────────────────────────────────────────────────

def test_direction_change_refused_while_servo_enabled():
    axis = _Axis()
    bar = _FakeElsBar(axis, servo_enable=1, direction=1, index=7)
    bar.update_feeds_ratio(bar, None)

    bar.toggle_feed_direction()

    assert bar.feed_direction == 1                     # unchanged
    assert (axis.syncRatioNum, axis.syncRatioDen) == (5, 4)


def test_direction_change_allowed_once_servo_is_off():
    axis = _Axis()
    bar = _FakeElsBar(axis, servo_enable=1, direction=1)
    bar.toggle_feed_direction()
    assert bar.feed_direction == 1

    bar.app.servo.servoEnable = 0
    bar.toggle_feed_direction()

    assert bar.feed_direction == -1


def test_explicit_set_is_also_interlocked():
    bar = _FakeElsBar(_Axis(), servo_enable=2, direction=1)   # mode 2 = jog

    bar.set_feed_direction(-1)

    assert bar.feed_direction == 1


# ── robustness ───────────────────────────────────────────────────────

def test_no_spindle_is_safe_in_left_hand():
    bar = _FakeElsBar(axis=None, direction=-1)

    bar.update_feeds_ratio(bar, None)                  # must not raise

    assert bar._feed_ratio is not None                 # still cached for a later flip


def test_reapply_without_a_feed_is_a_noop():
    axis = _Axis()
    bar = _FakeElsBar(axis, direction=-1)

    bar._reapply_feed_ratio()                          # nothing applied yet

    assert axis.syncRatioNum is None


def test_direction_sign_normalises_odd_values():
    bar = _FakeElsBar(_Axis(), direction=0)
    assert bar.direction_sign == 1                     # 0 is not negative -> right-hand
    bar.feed_direction = -7
    assert bar.direction_sign == -1
