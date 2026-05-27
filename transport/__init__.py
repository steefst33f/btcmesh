"""Transport abstraction layer for BTCMesh.

Provides abstract interface for device communication,
allowing different connection methods (serial, BLE) to be swapped.
"""

from transport.base import (
    BaseTransport,
    MessageHandler,
    TransportConnectionError,
    TransportError,
    TransportSendError,
)
from transport.meshtastic_serial import MeshtasticSerialTransport

__all__ = [
    "BaseTransport",
    "MeshtasticSerialTransport",
    "MessageHandler",
    "TransportConnectionError",
    "TransportError",
    "TransportSendError",
]
