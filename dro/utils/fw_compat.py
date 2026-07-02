"""Firmware↔software compatibility.

The software declares the minimum ("companion") firmware version it needs to expose all of
its features; the board dispatcher compares the connected firmware against it and the home
screen shows an update banner when the board is behind (tap → firmware screen → OTA update
from the online release list).

Bump COMPANION_FW_VERSION whenever the software starts using a protocol variable or command
introduced in a newer firmware release.
"""
import re

# v0.6.0: per-scale encoder input filter (`scales.filt`).
COMPANION_FW_VERSION = "v0.6.0"

# Accepts releases ("v0.6.0"), prereleases ("v0.6.0-beta.1") and git-describe dev builds
# ("v0.5.2-3-g1234abc[-dirty]"); the describe suffix does not affect ordering.
_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre_token>[A-Za-z]+)\.(?P<pre_n>\d+))?"
)


def parse_fw_version(version: str) -> tuple[int, int, int, int, int] | None:
    """Parse a firmware version string into an orderable key, or None if unparseable.

    Key: (major, minor, patch, is_release, prerelease_n) — a prerelease sorts before the
    release it precedes (v0.6.0-beta.1 < v0.6.0). Unparseable strings ("unknown", bare git
    hashes from builds outside a tagged checkout) return None.
    """
    m = _VERSION_RE.match((version or "").strip())
    if not m:
        return None
    is_release = 0 if m["pre_token"] else 1
    return (
        int(m["major"]),
        int(m["minor"]),
        int(m["patch"]),
        is_release,
        int(m["pre_n"] or 0),
    )


def fw_update_required(current: str, required: str = COMPANION_FW_VERSION) -> bool:
    """True when the `current` firmware is older than the `required` companion version.

    Unparseable current versions return False — we can't judge a dev build ("unknown",
    bare hash), and a false "update me" nag is worse than staying quiet.
    """
    cur = parse_fw_version(current)
    req = parse_fw_version(required)
    if cur is None or req is None:
        return False
    return cur < req
