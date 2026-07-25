"""Tests for the NetworkManager probe that keeps the app startable off-target.

The Pi image always has NetworkManager. Development hosts (WSL2, Windows, CI) may have no
nmcli binary at all, or the binary with the daemon stopped — both must report unavailable
rather than raising, because the network screen is built during app startup."""
import subprocess

import pytest

from dro.utils import platform


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """The probe is lru_cached, so each case needs a clean slate."""
    platform.network_manager_available.cache_clear()
    yield
    platform.network_manager_available.cache_clear()


def _fake_which(result):
    return lambda name: result


def test_missing_nmcli_binary(monkeypatch):
    """Windows and bare containers have no nmcli at all — no subprocess should be spawned."""
    monkeypatch.setattr(platform.shutil, "which", _fake_which(None))

    def explode(*a, **kv):
        raise AssertionError("must not shell out when nmcli is absent")

    monkeypatch.setattr(platform.subprocess, "run", explode)
    assert platform.network_manager_available() is False


def test_daemon_running(monkeypatch):
    monkeypatch.setattr(platform.shutil, "which", _fake_which("/usr/bin/nmcli"))
    monkeypatch.setattr(
        platform.subprocess, "run",
        lambda *a, **kv: subprocess.CompletedProcess(a, 0, stdout="connected", stderr=""),
    )
    assert platform.network_manager_available() is True


def test_binary_present_but_daemon_stopped(monkeypatch):
    """nmcli installed with NetworkManager not running exits non-zero."""
    monkeypatch.setattr(platform.shutil, "which", _fake_which("/usr/bin/nmcli"))
    monkeypatch.setattr(
        platform.subprocess, "run",
        lambda *a, **kv: subprocess.CompletedProcess(
            a, 8, stdout="", stderr="Error: NetworkManager is not running."),
    )
    assert platform.network_manager_available() is False


@pytest.mark.parametrize("error", [
    subprocess.TimeoutExpired(cmd="nmcli", timeout=5),
    OSError("exec format error"),
])
def test_probe_failures_are_not_fatal(monkeypatch, error):
    monkeypatch.setattr(platform.shutil, "which", _fake_which("/usr/bin/nmcli"))

    def raise_error(*a, **kv):
        raise error

    monkeypatch.setattr(platform.subprocess, "run", raise_error)
    assert platform.network_manager_available() is False


def test_result_is_cached(monkeypatch):
    """Callers sit on the once-per-second status path, so the probe must run only once."""
    monkeypatch.setattr(platform.shutil, "which", _fake_which("/usr/bin/nmcli"))
    calls = []

    def counted(*a, **kv):
        calls.append(a)
        return subprocess.CompletedProcess(a, 0, stdout="connected", stderr="")

    monkeypatch.setattr(platform.subprocess, "run", counted)
    assert platform.network_manager_available() is True
    assert platform.network_manager_available() is True
    assert len(calls) == 1
