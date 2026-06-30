"""drDRO RS-485 communication layer.

The custom CLI line protocol that replaces Modbus. This package is intentionally
**Kivy-free** infrastructure (stdlib logging, not kivy.logger) so it can be unit-tested
and driven standalone against hardware; the dispatcher layer above it uses kivy.logger.
"""
from dro.comms.protocol_client import (
    ProtocolClient,
    ProtocolError,
    Response,
    frame_request,
    parse_response,
    xor8,
)

__all__ = [
    "ProtocolClient",
    "ProtocolError",
    "Response",
    "frame_request",
    "parse_response",
    "xor8",
]
