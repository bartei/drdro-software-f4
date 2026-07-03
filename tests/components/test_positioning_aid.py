"""Tests for the PositioningAid (G2) derived geometry.

The AliasProperty getters are pure functions of the widget's properties, so we exercise the
real getter code against a lightweight stand-in — no GL/Window needed (matching the rest of
the suite, which tests logic without building the full Kivy app)."""
from types import SimpleNamespace

from dro.components.widgets.positioning_aid import PositioningAid


def _aid(value, span=1.0, tol=0.05, w=200, h=40):
    """Run the real getters against a stand-in and return the resolved geometry."""
    s = SimpleNamespace(value=value, span=span, tolerance=tol, width=w, height=h)
    s.dot_radius = PositioningAid._get_dot_radius(s)
    s.at_target = PositioningAid._get_at_target(s)
    s.fraction = PositioningAid._get_fraction(s)
    s.direction = PositioningAid._get_direction(s)
    s.bar_len = PositioningAid._get_bar_len(s)
    return s


def test_on_target_solid_dot_no_bar():
    on = _aid(0.0)
    assert on.at_target
    assert on.direction == 0        # bar collapses
    assert on.bar_len == 0.0


def test_tolerance_boundary_is_on_target():
    # exactly at the tolerance still counts as spot-on (dot solid)
    assert _aid(0.05).at_target
    assert not _aid(0.0500001).at_target


def test_offset_side_matches_sign():
    assert _aid(0.25).direction == 1     # positive offset -> bar to the right
    assert _aid(-0.5).direction == -1    # negative offset -> bar to the left


def test_fraction_scales_and_clamps():
    assert abs(_aid(0.25).fraction - 0.25) < 1e-9
    assert abs(_aid(-0.5).fraction - 0.5) < 1e-9
    assert _aid(5.0).fraction == 1.0     # beyond span -> pinned full
    assert _aid(0.0, span=0).fraction == 0.0  # guard against span<=0


def test_bar_len_uses_available_half_width():
    on = _aid(0.25)
    avail = 200 / 2 - 6 - on.dot_radius  # half width minus edge pad minus dot radius
    assert abs(on.bar_len - 0.25 * avail) < 1e-6


def test_dot_radius_clamped():
    assert _aid(0.0, h=40).dot_radius == 12.0    # min(h*0.3, 14)
    assert _aid(0.0, h=100).dot_radius == 14.0   # upper clamp
    assert _aid(0.0, h=2).dot_radius == 3.0      # lower clamp
