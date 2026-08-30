"""Board-aware firmware source selection.

The two boards take different, mutually incompatible images. The firmware projects give
their release assets distinct names precisely so an updater cannot cross them, and these
tests pin the host side of that contract: which repo gets queried, and which asset is
allowed to reach which board.
"""
import pytest

from dro.comms.updater import (
    FIRMWARE_SOURCES,
    LEGACY_F4,
    MAINBOARD_V15,
    FirmwareSource,
    FirmwareUpdater,
    detect_source,
)


class _Board:
    """Stand-in for the Board dispatcher: only `cached` and `connection` are touched here."""

    def __init__(self, settings: dict | None = None, raises: bool = False):
        self._settings = settings or {}
        self._raises = raises
        self.connection = object()

    def cached(self, name, idx=None):
        if self._raises:
            raise RuntimeError("no settings snapshot")
        return self._settings.get(name)


# ── detection ────────────────────────────────────────────────────────
def test_net_mac_identifies_the_v15_mainboard():
    board = _Board({"net.mac": "02:00:32:17:39:32", "scales.count": "5"})
    assert detect_source(board) is MAINBOARD_V15


def test_absent_net_registry_identifies_the_legacy_controller():
    # The old board's `settings` dump has scales/servo/diag only — no net.* at all.
    board = _Board({"servo.max": "720", "scales.num": "81,81,81,81", "diag.cycles": "12"})
    assert detect_source(board) is LEGACY_F4


def test_unknown_board_falls_back_to_the_legacy_controller():
    assert detect_source(_Board({})) is LEGACY_F4
    assert detect_source(_Board(raises=True)) is LEGACY_F4     # no snapshot yet / offline


@pytest.mark.parametrize("mac", [
    "02:00:32:17:39:32",          # a real assigned MAC
    "00:00:00:00:00:00",          # factory-flashed board, no MAC assigned yet (seen on the bench)
    "",                           # present but empty
])
def test_marker_presence_identifies_the_board_whatever_its_value(mac):
    """Detection keys on the variable existing, never on what it contains.

    A V1.5 board misread as the old controller would be offered an image that cannot run on
    it, so a degenerate value must not flip the answer.
    """
    assert detect_source(_Board({"net.mac": mac})) is MAINBOARD_V15


# ── asset matching: the anti-bricking contract ───────────────────────
def test_each_source_accepts_only_its_own_app_image():
    assert MAINBOARD_V15.matches("drdro-mainboard-app.bin")
    assert LEGACY_F4.matches("drdro-app.bin")
    assert not MAINBOARD_V15.matches("drdro-app.bin")
    assert not LEGACY_F4.matches("drdro-mainboard-app.bin")


@pytest.mark.parametrize("name", [
    "drdro-mainboard-bootloader.bin",
    "drdro-mainboard-factory.hex",
    "drdro-mainboard-app.elf",
    "SHA256SUMS.txt",
])
def test_non_application_assets_are_never_offered(name):
    for src in FIRMWARE_SOURCES:
        assert not src.matches(name), f"{src.key} accepted {name}"


def test_no_asset_can_be_offered_to_both_boards():
    """The decisive property: the two sources' accepted sets must not intersect."""
    names = [
        "drdro-app.bin", "drdro-mainboard-app.bin", "drdro-application.bin",
        "drdro-app-v2.bin", "drdro-mainboard-bootloader.bin", "app.bin",
    ]
    both = [n for n in names if MAINBOARD_V15.matches(n) and LEGACY_F4.matches(n)]
    assert both == [], f"assets accepted by both boards: {both}"


def test_legacy_loose_match_keeps_older_releases_reachable():
    # Releases predating the current naming still resolve on the old board...
    assert LEGACY_F4.matches("drdro-application.bin")
    # ...but the mainboard requires its exact asset, since every one of its releases has it.
    assert not MAINBOARD_V15.matches("drdro-mainboard-application.bin")


# ── updater wiring ───────────────────────────────────────────────────
def test_updater_targets_the_repo_of_the_connected_board():
    v15 = FirmwareUpdater(_Board({"net.mac": "02:00:32:17:39:32"}))
    old = FirmwareUpdater(_Board({"servo.max": "720"}))
    assert "drdro-mainboard" in v15.source.releases_url
    assert "drdro-firmware-f4" in old.source.releases_url


def test_source_is_detected_lazily_not_at_construction():
    """The screen builds its updater before the board has ever connected."""
    board = _Board({})                       # no snapshot yet
    updater = FirmwareUpdater(board)
    board._settings = {"net.mac": "02:00:32:17:39:32"}   # ...board connects afterwards
    assert updater.source is MAINBOARD_V15


def test_source_is_cached_then_re_detected_on_refresh():
    board = _Board({"net.mac": "02:00:32:17:39:32"})
    updater = FirmwareUpdater(board)
    assert updater.source is MAINBOARD_V15
    board._settings = {"servo.max": "720"}   # a different board is plugged in
    assert updater.source is MAINBOARD_V15   # cached — no silent switch mid-session
    assert updater.refresh_source() is LEGACY_F4


def test_an_explicit_source_is_never_overridden_by_detection():
    board = _Board({"net.mac": "02:00:32:17:39:32"})
    updater = FirmwareUpdater(board, source=LEGACY_F4)
    assert updater.source is LEGACY_F4
    assert updater.refresh_source() is LEGACY_F4


def test_sources_are_distinct_and_well_formed():
    assert len({s.key for s in FIRMWARE_SOURCES}) == len(FIRMWARE_SOURCES)
    assert len({s.repo for s in FIRMWARE_SOURCES}) == len(FIRMWARE_SOURCES)
    for src in FIRMWARE_SOURCES:
        assert isinstance(src, FirmwareSource)
        assert src.matches(src.asset), f"{src.key} rejects its own asset"
        assert src.releases_url.startswith("https://api.github.com/repos/")


# ── asset selection against real release payload shapes ──────────────
from dro.comms.updater import select_asset   # noqa: E402

_MAINBOARD_RELEASE = [
    {"name": "drdro-mainboard-app.bin", "browser_download_url": "u/app", "size": 82168},
    {"name": "drdro-mainboard-app.elf", "browser_download_url": "u/elf", "size": 1768876},
    {"name": "drdro-mainboard-bootloader.bin", "browser_download_url": "u/bl", "size": 12132},
    {"name": "drdro-mainboard-factory.hex", "browser_download_url": "u/fac", "size": 259532},
    {"name": "SHA256SUMS.txt", "browser_download_url": "u/sha", "size": 669},
]

_LEGACY_RELEASE = [
    {"name": "drdro-app.bin", "browser_download_url": "u/old", "size": 51000},
    {"name": "drdro-app.hex", "browser_download_url": "u/oldhex", "size": 140000},
]


def test_select_asset_picks_the_app_image_from_a_full_release():
    got = select_asset(_MAINBOARD_RELEASE, MAINBOARD_V15)
    assert got["name"] == "drdro-mainboard-app.bin"
    assert select_asset(_LEGACY_RELEASE, LEGACY_F4)["name"] == "drdro-app.bin"


def test_select_asset_refuses_a_release_built_for_the_other_board():
    """A mainboard release must yield nothing for the old controller — flashing it bricks."""
    assert select_asset(_MAINBOARD_RELEASE, LEGACY_F4) is None
    assert select_asset(_LEGACY_RELEASE, MAINBOARD_V15) is None


def test_select_asset_handles_a_release_with_no_assets():
    assert select_asset([], MAINBOARD_V15) is None
    assert select_asset([{"name": "notes.md"}], LEGACY_F4) is None
