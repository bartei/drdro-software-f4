import ctypes


def uint32_subtract_to_int32(a, b):
    """Wrap-around-safe delta of two unsigned 32-bit counters as a signed int32.

    The board reports encoder/step positions as uint32 (`scales.pos`, `servo.pos`); the
    host accumulates motion by differencing consecutive samples. Doing the subtraction in
    uint32 then reinterpreting as int32 gives the correct signed delta across the 2^32 wrap.
    """
    return ctypes.c_int32(ctypes.c_uint32(a).value - ctypes.c_uint32(b).value).value
