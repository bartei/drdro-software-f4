"""Tests for the Board bridge logic that does not require the live link or full Kivy app:
the pure `sta`→fast_data_values mapping and the settings-cache reader, plus the v1.5
transport selection, dynamic scale count, and live reconfigure (built with a real Board but
no open port — the link opens lazily inside `run()`)."""
import asyncio

from kivy.event import EventDispatcher
from kivy.properties import NumericProperty

from dro.comms.protocol_client import parse_response, xor8
from dro.dispatchers.board import Board, map_sta
from dro.dispatchers.formats import FormatsDispatcher


class _OffsetProvider(EventDispatcher):
    """Minimal stand-in for MainApp as the axes' offset source (needs a bindable offset)."""
    currentOffset = NumericProperty(0)
    abs_mode = False

    def get_spindle_axis(self):
        return None


def _make_board(**kw):
    return Board(formats=FormatsDispatcher(id_override="0"),
                 offset_provider=_OffsetProvider(), **kw)


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


# ── v1.5: transport selection ────────────────────────────────────────
def test_serial_transport_is_default():
    b = _make_board(transport="serial", port="/dev/null")
    assert b.connection.kind == "serial"
    assert b.scale_count == 4 and len(b.inputs) == 4     # v1.0 default, no phantom 5th axis


def test_tcp_transport_selected():
    b = _make_board(transport="tcp", host="10.0.0.5", tcp_port=5555)
    assert b.connection.kind == "tcp"
    assert b.connection.description == "tcp://10.0.0.5:5555"


def test_tcp_blank_host_stays_tcp_not_serial():
    # A blank tcp host is "not configured yet", must NOT silently fall back to serial.
    b = _make_board(transport="tcp", host="")
    assert b.connection.kind == "tcp"


# ── v1.5: dynamic scale count (4 vs 5 axis boards) ───────────────────
def test_apply_scale_count_grows_to_five():
    b = _make_board(transport="serial", port="/dev/null")
    b._apply_scale_count(5)
    assert len(b.inputs) == 5 and b.scale_count == 5


def test_apply_scale_count_shrinks_back_to_four():
    b = _make_board(transport="serial", port="/dev/null")
    b._apply_scale_count(5)
    b._apply_scale_count(4)
    assert len(b.inputs) == 4 and b.scale_count == 4


def test_apply_scale_count_equal_is_noop():
    b = _make_board(transport="serial", port="/dev/null")
    before = list(b.inputs)
    b._apply_scale_count(4)
    assert list(b.inputs) == before and b.scale_count == 4


# ── v1.5: live reconfigure (serial ↔ tcp without app restart) ────────
def test_reconfigure_serial_to_tcp():
    b = _make_board(transport="serial", port="/dev/null")

    async def go():
        assert b.connection.kind == "serial"
        b.reconfigure(transport="tcp", host="192.168.0.7")
        await asyncio.sleep(0)          # let the old-connection close task run on the loop
        return b.connection

    conn = asyncio.run(go())
    assert conn.kind == "tcp" and conn.description == "tcp://192.168.0.7:5555"
    assert b.connected is False         # forced down until the new pipe reopens
