"""Tests for the Board bridge logic that does not require the live link or full Kivy app:
the pure `sta`→fast_data_values mapping and the settings-cache reader."""
from dro.comms.protocol_client import parse_response, xor8
from dro.dispatchers.board import Board, map_sta


def _frame(lines):
    body = "".join(l + "\n" for l in lines)
    return parse_response(lines + [f"crc={xor8(body.encode()):02X}"])


def test_map_sta_full():
    r = _frame([
        "scales.pos=10,20,0,0", "scales.speed=5,0,0,0",
        "servo.pos=1234", "servo.speed=7.5", "servo.tgt=-42", "servo.mode=2",
    ])
    fd = map_sta(r)
    assert fd["scaleCurrent"] == [10, 20, 0, 0]
    assert fd["scaleSpeed"] == [5, 0, 0, 0]
    assert fd["servoCurrent"] == 1234
    assert fd["servoSpeed"] == 7.5
    assert fd["stepsToGo"] == -42
    assert fd["servoEnable"] == 2          # firmware servoMode → legacy servoEnable key


def test_map_sta_defaults_on_empty():
    fd = map_sta(_frame([]))               # crc-valid empty frame
    assert fd["scaleCurrent"] == [0, 0, 0, 0]
    assert fd["scaleSpeed"] == [0, 0, 0, 0]
    assert fd["servoCurrent"] == 0 and fd["stepsToGo"] == 0 and fd["servoEnable"] == 0


def test_cached_scalar_and_array():
    # Build a bare Board (no __init__) just to exercise cached() against a settings snapshot.
    b = Board.__new__(Board)
    b._settings = _frame(["servo.max=720", "scales.sync=0,1,0,0"])
    assert b.cached("servo.max") == "720"
    assert b.cached("scales.sync", 1) == "1"
    assert b.cached("scales.sync", 9) is None      # out of range
    assert b.cached("missing") is None


def test_cached_without_snapshot():
    b = Board.__new__(Board)
    b._settings = None
    assert b.cached("servo.max") is None
