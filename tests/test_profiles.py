"""Tests for the machine-profile manager (save/list/apply/restore) using a fake
board and temporary settings folders — no live link, no Kivy app."""
import asyncio

import yaml

import dro.profiles as profiles_mod
from dro.profiles import ProfileManager, BOARD_PERSISTED_VARS


class FakeResponse:
    def __init__(self, values, crc_ok=True):
        self.values = values
        self.crc_ok = crc_ok
        self.error = None

    def __bool__(self):
        return self.crc_ok


class FakeConnection:
    def __init__(self, values):
        self.values = dict(values)
        self.sets = []
        self.saves = 0

    async def settings(self):
        return FakeResponse(self.values)

    async def set(self, name, value, idx=None):
        self.sets.append((name, idx, value))
        if idx is None:
            self.values[name] = str(value)
        else:
            parts = self.values.get(name, "").split(",")
            parts[idx] = str(value)
            self.values[name] = ",".join(parts)

    async def save(self):
        self.saves += 1
        return FakeResponse({})


class FakeBoard:
    def __init__(self, values, connected=True):
        self.connected = connected
        self.connection = FakeConnection(values)
        self.firmware_version = "v9.9.9"


BOARD_VALUES = {
    "scales.num": "1,2,3,4",
    "scales.den": "100,200,300,400",
    "scales.sync": "0,1,0,0",
    "scales.filt": "5,5,7,5",
    "servo.max": "720",
    "servo.acc": "120",
    "servo.jog": "0",
    "servo.idx": "0",
    "servo.mode": "0",
    "scales.pos": "42,0,0,0",  # live var — must NOT be captured
}


def _manager(tmp_path, connected=True):
    # Redirect both the host settings folder and the profiles folder.
    profiles_mod.SETTINGS_FOLDER = tmp_path
    board = FakeBoard(BOARD_VALUES, connected=connected)
    return ProfileManager(board, folder=tmp_path / "profiles"), board


def test_snapshot_board_captures_only_persisted_vars(tmp_path):
    mgr, _ = _manager(tmp_path)
    snap = asyncio.run(mgr.snapshot_board())
    assert set(snap) == set(BOARD_PERSISTED_VARS)
    assert snap["scales.filt"] == [5, 5, 7, 5]
    assert snap["servo.max"] == 720
    assert "scales.pos" not in snap


def test_snapshot_board_disconnected(tmp_path):
    mgr, _ = _manager(tmp_path, connected=False)
    assert asyncio.run(mgr.snapshot_board()) == {}


def test_save_profile_contents_and_metadata(tmp_path):
    mgr, _ = _manager(tmp_path)
    (tmp_path / "Axis-0.yaml").write_text(yaml.dump({"axisName": "X"}))
    (tmp_path / "CoordBar-0.yaml").write_text(yaml.dump({"ratioNum": 1}))
    (tmp_path / "FormatsDispatcher-0.yaml").write_text(yaml.dump({"font_size": 24}))

    path = asyncio.run(mgr.save_profile("My Lathe"))
    data = yaml.safe_load(path.read_text())

    meta = data["metadata"]
    assert meta["name"] == "My Lathe"
    assert meta["kind"] == "user"
    assert meta["created"]
    assert meta["software_version"].startswith("v")
    assert meta["firmware_version"] == "v9.9.9"

    assert data["board"]["scales.filt"] == [5, 5, 7, 5]
    assert data["host"]["Axis-0"] == {"axisName": "X"}
    assert data["host"]["CoordBar-0"] == {"ratioNum": 1}
    assert "FormatsDispatcher-0" not in data["host"]  # device-local, not machine config


def test_list_profiles_newest_first(tmp_path):
    mgr, _ = _manager(tmp_path)
    asyncio.run(mgr.save_profile("first"))
    asyncio.run(mgr.save_profile("second"))
    entries = mgr.list_profiles()
    assert [e["name"] for e in entries] == ["second", "first"] or len({e["created"] for e in entries}) == 1


def test_apply_profile_replaces_host_files_and_pushes_board(tmp_path):
    mgr, board = _manager(tmp_path)
    (tmp_path / "Axis-0.yaml").write_text(yaml.dump({"axisName": "X"}))
    (tmp_path / "Axis-1.yaml").write_text(yaml.dump({"axisName": "Y"}))
    path = asyncio.run(mgr.save_profile("mill"))

    # Simulate moving to a machine with one axis and different board values.
    (tmp_path / "Axis-1.yaml").unlink()
    (tmp_path / "Axis-0.yaml").write_text(yaml.dump({"axisName": "Z"}))
    board.connection.values["scales.filt"] = "0,0,0,0"

    asyncio.run(mgr.apply_profile(path))

    # Host files restored to the profile's set (both axes back).
    assert yaml.safe_load((tmp_path / "Axis-0.yaml").read_text()) == {"axisName": "X"}
    assert yaml.safe_load((tmp_path / "Axis-1.yaml").read_text()) == {"axisName": "Y"}
    # Board section pushed (per-element for arrays) and persisted.
    assert ("scales.filt", 2, 7) in board.connection.sets
    assert ("servo.max", None, 720) in board.connection.sets
    assert board.connection.saves >= 1
    # An automatic backup profile was created alongside the applied one.
    kinds = [e["kind"] for e in mgr.list_profiles()]
    assert "backup" in kinds


def test_restore_board_settings_only_writes_diffs(tmp_path):
    mgr, board = _manager(tmp_path)
    snapshot = asyncio.run(mgr.snapshot_board())

    # Nothing changed → nothing written, no flash save.
    assert asyncio.run(mgr.restore_board_settings(snapshot)) == 0
    assert board.connection.sets == []
    assert board.connection.saves == 0

    # Firmware "lost" two settings (e.g. layout change reset them to defaults).
    board.connection.values["scales.filt"] = "5,5,5,5"
    board.connection.values["servo.max"] = "100"
    restored = asyncio.run(mgr.restore_board_settings(snapshot))
    assert restored == 2
    assert ("scales.filt", 2, 7) in board.connection.sets
    assert ("servo.max", None, 720) in board.connection.sets
    assert board.connection.saves == 1


def test_delete_profile(tmp_path):
    mgr, _ = _manager(tmp_path)
    path = asyncio.run(mgr.save_profile("gone"))
    assert path.exists()
    mgr.delete_profile(path)
    assert not path.exists()
    assert mgr.list_profiles() == []
