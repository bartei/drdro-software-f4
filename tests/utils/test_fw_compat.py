from dro.utils.fw_compat import (
    COMPANION_FW_VERSION,
    fw_update_required,
    parse_fw_version,
)


def test_companion_version_is_parseable():
    assert parse_fw_version(COMPANION_FW_VERSION) is not None


def test_parse_release():
    assert parse_fw_version("v0.6.0") == (0, 6, 0, 1, 0)
    assert parse_fw_version("0.6.0") == (0, 6, 0, 1, 0)
    assert parse_fw_version("v1.12.3") == (1, 12, 3, 1, 0)


def test_parse_prerelease():
    assert parse_fw_version("v0.6.0-beta.1") == (0, 6, 0, 0, 1)
    assert parse_fw_version("v0.6.0-rc.2") == (0, 6, 0, 0, 2)


def test_parse_git_describe_suffix_ignored():
    # dev build N commits after a tag — same ordering as the tag itself
    assert parse_fw_version("v0.5.2-3-g1234abc") == (0, 5, 2, 1, 0)
    assert parse_fw_version("v0.5.2-3-g1234abc-dirty") == (0, 5, 2, 1, 0)
    assert parse_fw_version("v0.6.0-beta.1-3-g1234abc") == (0, 6, 0, 0, 1)


def test_parse_garbage_returns_none():
    assert parse_fw_version("unknown") is None
    assert parse_fw_version("") is None
    assert parse_fw_version("g1234abc") is None  # --always fallback: bare hash


def test_update_required_for_older_firmware():
    assert fw_update_required("v0.5.2", "v0.6.0") is True
    assert fw_update_required("v0.5.2-14-gabc123-dirty", "v0.6.0") is True


def test_update_not_required_for_current_or_newer():
    assert fw_update_required("v0.6.0", "v0.6.0") is False
    assert fw_update_required("v0.6.0-3-g1234abc", "v0.6.0") is False
    assert fw_update_required("v0.6.1", "v0.6.0") is False
    assert fw_update_required("v0.7.0", "v0.6.0") is False
    assert fw_update_required("v1.0.0", "v0.6.0") is False


def test_prerelease_of_required_version_is_older():
    assert fw_update_required("v0.6.0-beta.1", "v0.6.0") is True
    assert fw_update_required("v0.6.1-beta.1", "v0.6.0") is False


def test_unparseable_current_never_nags():
    assert fw_update_required("unknown", "v0.6.0") is False
    assert fw_update_required("", "v0.6.0") is False