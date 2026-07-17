"""ELS enable button couples servo output with spindle sync (headless).

Bug: enabling the servo on the ELS page did nothing useful because the spindle was
never armed as the sync source — the only workaround was to enable the spindle from
the Jog/DRO page first. `ElsBar.toggle_servo` now toggles the servo (servo.mode 1 =
sync+index) AND the spindle input's `scales.sync` together, so ELS works from the ELS
page alone. These tests exercise the real toggle_servo → toggle_enable/toggle_sync path.
"""
from fractions import Fraction

import pytest

from dro.dispatchers import saving_dispatcher
from dro.dispatchers.axis import AxisDispatcher
from dro.dispatchers.axis_transform import AxisTransform
from dro.dispatchers.servo import ServoDispatcher
from dro.components.home.elsbar import ElsBar


class _MockBoard:
    def __init__(self):
        self.connected = True
        self.fast_data_values = {
            "servoCurrent": 0, "servoSpeed": 0, "stepsToGo": 0, "servoEnable": 0,
            "scaleCurrent": [0, 0, 0, 0], "scaleSpeed": [0, 0, 0, 0],
        }
        self.writes = []            # (name, value, idx)
        self.spindle_axis = None    # set to the AxisDispatcher after construction

    def bind(self, **kwargs):
        pass

    def write(self, name, value, idx=None):
        self.writes.append((name, value, idx))

    def write_persisted(self, name, value, idx=None):
        self.writes.append((name, value, idx))

    def cached(self, name, idx=None):
        return None

    def get_spindle_axis(self):
        return self.spindle_axis


class _Fmt:
    angle_format = "{:.3f}"
    angle_speed_format = "{:.3f}"
    position_format = "{:.3f}"
    speed_format = "{:.3f}"
    current_format = "MM"
    metric_speed_unit = "m/min"
    imperial_speed_unit = "ft/min"
    factor = Fraction(1, 1)

    def bind(self, **kwargs):
        pass


class _OffsetProvider:
    currentOffset = 0
    abs_mode = False

    def bind(self, **kwargs):
        pass


class _Input:
    """Minimal InputDispatcher stand-in for the axis position/sync-ratio math."""
    scaled_value = 0.0
    ratioNum = 1
    ratioDen = 1
    stepsPerMM = 1000
    steps_per_second = 0.0


class _FakeApp:
    def __init__(self, servo, board):
        self.servo = servo
        self.board = board


class _FakeElsBar:
    """Duck-typed `self` for calling the unbound ElsBar.toggle_servo (avoids a live app)."""
    def __init__(self, app):
        self.app = app


def _scales_sync_writes(board):
    return [w for w in board.writes if w[0] == "scales.sync"]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(saving_dispatcher, "SETTINGS_FOLDER", tmp_path)
    board = _MockBoard()
    fmt = _Fmt()
    servo = ServoDispatcher(board=board, formats=fmt, id_override="0")
    spindle = AxisDispatcher(
        board=board, formats=fmt, servo=servo,
        offset_provider=_OffsetProvider(), inputs=[_Input()],
        transform=AxisTransform.identity(0), id_override="spindle",
    )
    board.spindle_axis = spindle
    els_bar = _FakeElsBar(_FakeApp(servo, board))
    return board, servo, spindle, els_bar


def test_enabling_servo_arms_spindle_sync(rig):
    board, servo, spindle, els_bar = rig
    assert servo.servoEnable == 0 and spindle.syncEnable is False

    board.writes.clear()
    ElsBar.toggle_servo(els_bar)

    assert servo.servoEnable == 1
    assert spindle.syncEnable is True
    assert ("scales.sync", 1, 0) in board.writes


def test_disabling_servo_disarms_spindle_sync(rig):
    board, servo, spindle, els_bar = rig
    ElsBar.toggle_servo(els_bar)        # on
    assert servo.servoEnable == 1 and spindle.syncEnable is True

    board.writes.clear()
    ElsBar.toggle_servo(els_bar)        # off

    assert servo.servoEnable == 0
    assert spindle.syncEnable is False
    assert ("scales.sync", 0, 0) in board.writes


def test_already_armed_spindle_is_not_toggled_off_when_enabling(rig):
    """If the spindle was already synced (e.g. from the Jog page), enabling the servo
    must leave it armed — not flip it off via a blind toggle."""
    board, servo, spindle, els_bar = rig
    spindle.syncEnable = True           # already armed elsewhere

    board.writes.clear()
    ElsBar.toggle_servo(els_bar)        # servo off -> on

    assert servo.servoEnable == 1
    assert spindle.syncEnable is True
    assert _scales_sync_writes(board) == []   # no redundant sync write


def test_no_spindle_configured_is_a_noop_for_sync(rig):
    board, servo, spindle, els_bar = rig
    board.spindle_axis = None           # no spindle role assigned

    board.writes.clear()
    ElsBar.toggle_servo(els_bar)

    assert servo.servoEnable == 1       # servo still toggles
    assert _scales_sync_writes(board) == []