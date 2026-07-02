"""
STM32 TIM input-capture filter (ICxF) timing math.

The hardware filter samples the encoder input at a divided timer clock and
requires N consecutive identical samples before an edge is accepted, so any
pulse shorter than N * divider / f_DTS is rejected as noise.  On the drDRO
board all four encoder timers run with CKD = DIV1, making f_DTS equal to the
100 MHz timer clock.

Divider/N table: STM32F411 reference manual (RM0383), TIMx_CCMR1 ICxF field.
"""

TIMER_CLOCK_HZ = 100_000_000  # f_DTS on the drDRO F411 board (CKD = DIV1)

FILTER_MAX = 15  # ICxF is a 4-bit field

# ICxF value -> (sampling-clock divider, consecutive samples required)
_DIV_N = {
    0: (1, 0),  # filter disabled
    1: (1, 2),
    2: (1, 4),
    3: (1, 8),
    4: (2, 6),
    5: (2, 8),
    6: (4, 6),
    7: (4, 8),
    8: (8, 6),
    9: (8, 8),
    10: (16, 5),
    11: (16, 6),
    12: (16, 8),
    13: (32, 5),
    14: (32, 6),
    15: (32, 8),
}


def reject_time_s(value: int) -> float:
    """Longest pulse the filter rejects, in seconds (0.0 = no filtering)."""
    div, n = _DIV_N[int(value)]
    return n * div / TIMER_CLOCK_HZ


def max_frequency_hz(value: int) -> float:
    """Highest quadrature signal frequency (per channel) that still passes.

    Each channel level must persist longer than the reject time, so a square
    wave passes while its half-period exceeds it: f_max = 1 / (2 * t_reject).
    """
    t = reject_time_s(value)
    if t == 0.0:
        return float("inf")
    return 1.0 / (2.0 * t)


def format_time(seconds: float) -> str:
    if seconds >= 1e-6:
        return f"{seconds * 1e6:.3g} µs"
    return f"{seconds * 1e9:.3g} ns"


def format_frequency(hz: float) -> str:
    if hz >= 1e6:
        return f"{hz / 1e6:.3g} MHz"
    return f"{hz / 1e3:.3g} kHz"


def describe(value: int) -> str:
    """One-line summary for the settings UI info label."""
    if int(value) == 0:
        return "no filtering — accepts any pulse width"
    t = reject_time_s(value)
    f = max_frequency_hz(value)
    return f"rejects pulses < {format_time(t)}  ·  max ≈ {format_frequency(f)}"
