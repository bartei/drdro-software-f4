"""Tests for the encoder input-filter timing math (STM32 TIM ICxF table)."""
import math

from dro.utils import encoder_filter as ef


def test_table_covers_full_range():
    for v in range(ef.FILTER_MAX + 1):
        assert ef.reject_time_s(v) >= 0.0
        assert ef.max_frequency_hz(v) > 0.0
        assert ef.describe(v)


def test_zero_disables_filtering():
    assert ef.reject_time_s(0) == 0.0
    assert ef.max_frequency_hz(0) == math.inf
    assert "no filtering" in ef.describe(0)


def test_known_values_at_100mhz():
    # ICxF=1: f_CK_INT, N=2 → 20 ns
    assert ef.reject_time_s(1) == 2 / 100e6
    # ICxF=5 (default): f_DTS/2, N=8 → 160 ns → 3.125 MHz max
    assert ef.reject_time_s(5) == 16 / 100e6
    assert ef.max_frequency_hz(5) == 1 / (2 * 160e-9)
    # ICxF=15: f_DTS/32, N=8 → 2.56 µs → 195.3125 kHz max
    assert ef.reject_time_s(15) == 256 / 100e6
    assert ef.max_frequency_hz(15) == 1 / (2 * 2.56e-6)


def test_reject_time_monotonic():
    times = [ef.reject_time_s(v) for v in range(ef.FILTER_MAX + 1)]
    assert times == sorted(times)


def test_describe_default():
    d = ef.describe(5)
    assert "160 ns" in d
    assert "MHz" in d


def test_format_units():
    assert ef.format_time(160e-9) == "160 ns"
    assert ef.format_time(2.56e-6) == "2.56 µs"
    assert ef.format_frequency(25e6) == "25 MHz"
    assert ef.format_frequency(195312.5) == "195 kHz"
