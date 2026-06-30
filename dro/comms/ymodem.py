"""Self-contained YMODEM sender (CRC-16, 1024-byte STX blocks) — matches the drDRO
bootloader's receiver (bootloader/src/ymodem.c). Ported from tools/dro_update.py, made a
library: raises :class:`YmodemError` instead of exiting, and reports progress via a callback.

Baud is fixed at 115200 (hardware limit). The bootloader is the receiver.
"""
from __future__ import annotations

import os
import time

SOH, STX, EOT, ACK, NAK, CAN, CRC_C, SUB = 0x01, 0x02, 0x04, 0x06, 0x15, 0x18, 0x43, 0x1A
DATA_LEN = 1024


class YmodemError(Exception):
    pass


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return crc


def _make_block(seq: int, payload: bytes) -> bytes:
    head = SOH if len(payload) == 128 else STX
    c = crc16(payload)
    return bytes([head, seq & 0xFF, (~seq) & 0xFF]) + payload + bytes([c >> 8, c & 0xFF])


def _wait_for(ser, want, timeout):
    """Discard bytes until `want` arrives (tolerates the RS485 turnaround glitch)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        b = ser.read(1)
        if b and b[0] == want:
            return True
    return False


def _wait_ack(ser, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        b = ser.read(1)
        if b and b[0] in (ACK, NAK, CAN):
            return b[0]
    return None


def _send_block(ser, block, retries=10):
    for _ in range(retries):
        ser.write(block)
        ser.flush()
        r = _wait_ack(ser)
        if r == ACK:
            return True
        if r == CAN:
            raise YmodemError("bootloader cancelled the transfer (CAN)")
    return False


def ymodem_send(ser, path: str, on_progress=None) -> int:
    """Send `path` over `ser` via YMODEM. Calls on_progress(sent_bytes, total_bytes) as it
    goes. Returns the byte count. Raises YmodemError on failure."""
    with open(path, "rb") as f:
        data = f.read()
    name = os.path.basename(path).encode()
    size = len(data)

    if not _wait_for(ser, CRC_C, 30.0):
        raise YmodemError("no YMODEM handshake ('C') — did `flash <bank>` start?")
    header = (name + b"\x00" + str(size).encode() + b"\x00").ljust(128, b"\x00")
    if not _send_block(ser, _make_block(0, header)):
        raise YmodemError("header (block 0) not acked")
    if not _wait_for(ser, CRC_C, 5.0):
        raise YmodemError("no 'C' after header")

    seq = 1
    if on_progress:
        on_progress(0, size)
    for off in range(0, size, DATA_LEN):
        chunk = data[off:off + DATA_LEN].ljust(DATA_LEN, bytes([SUB]))
        if not _send_block(ser, _make_block(seq, chunk)):
            raise YmodemError(f"block {seq} not acked")
        seq += 1
        if on_progress:
            on_progress(min(off + DATA_LEN, size), size)

    for _ in range(10):                       # EOT (NAK'd once, then ACK'd)
        ser.write(bytes([EOT]))
        ser.flush()
        if _wait_ack(ser) == ACK:
            break
    else:
        raise YmodemError("EOT not acked")
    if _wait_for(ser, CRC_C, 5.0):            # trailing null header closes the batch
        _send_block(ser, _make_block(0, b"\x00" * 128))
    return size
