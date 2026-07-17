"""feeds.custom_feed: user-entered arbitrary feed → leadscrew mm-per-rev ratio.

Ratios must be exact (Fraction) and match the preconfigured tables' unit conventions so a
custom value equal to a table entry produces the identical ratio.
"""
from fractions import Fraction

import pytest

from dro import feeds


def test_thread_mm_is_pitch_in_mm():
    fc = feeds.custom_feed("Thread MM", 1.3)
    assert fc.ratio == Fraction(13, 10)
    assert fc.name == "1.3"


def test_feed_mm_is_mm_per_rev():
    fc = feeds.custom_feed("Feed MM", 0.15)
    assert fc.ratio == Fraction(15, 100)


def test_thread_in_is_25_4_over_tpi():
    fc = feeds.custom_feed("Thread IN", 11.5)
    assert fc.ratio == Fraction(254, 10) / Fraction(23, 2)   # 25.4 / 11.5
    assert fc.name == "11.5"


def test_feed_in_is_25_4_times_value():
    fc = feeds.custom_feed("Feed IN", 0.005)
    assert fc.ratio == Fraction(254, 10) * Fraction(5, 1000)


def test_custom_matches_table_entry_when_value_coincides():
    # Entering a value that already exists in a table yields the same ratio.
    assert feeds.custom_feed("Thread IN", 20).ratio == feeds.THREAD_IN[
        [f.name for f in feeds.THREAD_IN].index("20")
    ].ratio
    assert feeds.custom_feed("Thread MM", 1.0).ratio == Fraction("1")


@pytest.mark.parametrize("bad", [0, -1, -0.5])
def test_non_positive_value_rejected(bad):
    with pytest.raises(ValueError):
        feeds.custom_feed("Thread MM", bad)


def test_unknown_table_rejected():
    with pytest.raises(ValueError):
        feeds.custom_feed("Nope", 1.0)