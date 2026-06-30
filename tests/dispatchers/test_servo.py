"""ServoDispatcher indexing-speed behavior (headless, no live link / window).

Locks in the design where the indexing feedrate is the board-owned, persisted `servo.idx`
caught by the firmware ramp generator — the host must NOT override `servo.max` for a move
(that throttled the step-pulse cadence a simultaneous sync follower rides on)."""
import pytest

from dro.dispatchers import saving_dispatcher
from dro.dispatchers.servo import ServoDispatcher


class _MockBoard:
    def __init__(self):
        self.connected = True
        self.fast_data_values = {
            "servoCurrent": 0, "servoSpeed": 0, "stepsToGo": 0, "servoEnable": 1,
        }
        self.writes = []           # (name, value) live sets
        self.persisted = []        # (name, value) set+save

    def bind(self, **kwargs):      # ServoDispatcher binds connected/update_tick — no-op here
        pass

    def write(self, name, value, idx=None):
        self.writes.append((name, value))

    def write_persisted(self, name, value, idx=None):
        self.persisted.append((name, value))

    def cached(self, name, idx=None):
        return None


class _Fmt:
    angle_format = "{:.3f}"
    position_format = "{:.3f}"
    factor = 1.0
    current_format = "metric"

    def bind(self, **kwargs):
        pass


@pytest.fixture
def servo(tmp_path, monkeypatch):
    # Redirect per-component YAML persistence to a temp dir (no ~/.config writes).
    monkeypatch.setattr(saving_dispatcher, "SETTINGS_FOLDER", tmp_path)
    s = ServoDispatcher(board=_MockBoard(), formats=_Fmt())
    s.update_positions()           # populate step_positions for the 12 divisions
    return s


def test_index_move_does_not_override_max_speed(servo):
    board = servo.board
    servo.servoEnable = 1
    board.writes.clear()

    servo.go_next()                # index 0 -> 1, fires on_index

    names = [n for n, _ in board.writes]
    assert "servo.tgt" in names                 # the move was issued
    assert "servo.max" not in names             # ...but the mechanical ceiling was untouched
    assert servo.disableControls is True
    assert servo._move_pending is True


def test_offset_move_does_not_override_max_speed(servo):
    board = servo.board
    servo.servoEnable = 1
    board.writes.clear()

    servo.offset = servo.offset + 30.0          # fires on_offset

    names = [n for n, _ in board.writes]
    assert "servo.tgt" in names
    assert "servo.max" not in names


def test_index_speed_is_persisted_to_board(servo):
    board = servo.board
    board.persisted.clear()

    servo.indexSpeed = 150                       # fires on_indexSpeed

    assert ("servo.idx", 150) in board.persisted


def test_move_complete_reenables_controls_only_after_move_observed(servo):
    """The _move_pending latch must not re-enable controls on a stale stepsToGo==0."""
    board = servo.board
    servo.servoEnable = 1
    servo.go_next()
    assert servo.disableControls is True and servo._move_pending is True

    # Stale poll: move not yet observed underway -> controls stay disabled.
    board.fast_data_values["stepsToGo"] = 0
    servo.on_update_tick(board, None)
    assert servo.disableControls is True

    # Move observed running -> latch clears.
    board.fast_data_values["stepsToGo"] = 500
    servo.on_update_tick(board, None)
    assert servo._move_pending is False

    # Move finished -> controls re-enabled, and no servo.max restore happens.
    board.writes.clear()
    board.fast_data_values["stepsToGo"] = 0
    servo.on_update_tick(board, None)
    assert servo.disableControls is False
    assert "servo.max" not in [n for n, _ in board.writes]
