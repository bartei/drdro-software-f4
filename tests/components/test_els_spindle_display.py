"""ELS spindle info hides the angular position once the spindle spins too fast to read.

The RPM readout always stays; only the small degrees line is suppressed above
POSITION_HIDE_RPM. Drives the real ElsSpindleInfo._update_spindle on a duck-typed self.
"""
from dro.components.home.els_mode_layout import (
    ElsSpindleInfo, POSITION_HIDE_RPM, POSITION_HIDDEN, ICON_STOP,
)


class _Axis:
    def __init__(self, speed, scaledPosition=90.0, formattedPosition="100"):
        self.speed = speed
        self.scaledPosition = scaledPosition
        self.formattedPosition = formattedPosition


class _Els:
    def __init__(self, axis):
        self._axis = axis

    def get_spindle_axis(self):
        return self._axis


class _Fmt:
    position_format = "{:.3f}"


class _App:
    def __init__(self, axis):
        self.els = _Els(axis)
        self.formats = _Fmt()


class _FakeInfo:
    """Stand-in for ElsSpindleInfo (its __init__ needs a live app)."""
    def __init__(self, axis):
        self.app = _App(axis)
        self.spindle_rpm = "--"
        self.spindle_position = "--"
        self.direction_icon = ICON_STOP


def _run(axis):
    info = _FakeInfo(axis)
    ElsSpindleInfo._update_spindle(info)
    return info


def test_position_shown_when_slow():
    info = _run(_Axis(speed=5.0, scaledPosition=90.0))
    assert info.spindle_position == "90.000°"


def test_position_hidden_when_spinning_fast():
    info = _run(_Axis(speed=POSITION_HIDE_RPM + 5, scaledPosition=90.0))
    assert info.spindle_position == POSITION_HIDDEN


def test_position_hidden_for_fast_reverse():
    info = _run(_Axis(speed=-(POSITION_HIDE_RPM + 5), scaledPosition=90.0))
    assert info.spindle_position == POSITION_HIDDEN


def test_position_shown_at_threshold_boundary():
    # Strict '>' — exactly at the threshold still shows the position.
    info = _run(_Axis(speed=POSITION_HIDE_RPM, scaledPosition=90.0))
    assert info.spindle_position == "90.000°"


def test_rpm_still_shown_when_position_hidden():
    info = _run(_Axis(speed=POSITION_HIDE_RPM + 5, formattedPosition="1234"))
    assert info.spindle_position == POSITION_HIDDEN
    assert info.spindle_rpm == "1234"      # RPM readout is untouched