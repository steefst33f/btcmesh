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
from transport.factory import get_transport
from transport.meshcore_serial import MeshCoreSerialTransport
from transport.meshtastic_serial import MeshtasticSerialTransport

__all__ = [
    "BaseTransport",
    "MeshCoreSerialTransport",
    "MeshtasticSerialTransport",
    "MessageHandler",
    "TransportConnectionError",
    "TransportError",
    "TransportSendError",
    "get_transport",
]
