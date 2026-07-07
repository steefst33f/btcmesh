"""Abstract base class for BTCMesh transport implementations.

Defines the interface that all transport backends must implement.
Consumers (CLI, server, GUI) depend on this interface rather than
on concrete library details.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TransportError(Exception):
    """Base exception for all transport-related errors."""
    pass


class TransportConnectionError(TransportError):
    """Raised when connecting to a device fails.

    Examples: no device found, permission denied, device busy,
    library not installed.
    """
    pass


class TransportSendError(TransportError):
    """Raised when sending a message fails.

    Examples: device disconnected during send, message too long,
    invalid destination.
    """
    pass


# ---------------------------------------------------------------------------
# Type alias for the message handler callback
# ---------------------------------------------------------------------------

MessageHandler = Callable[[str, str], None]
"""Callback signature for received messages.

Args:
    message_text: The decoded text content of the message.
    sender_id: The sender's node identifier (format depends on transport).
"""


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseTransport(ABC):
    """Abstract base class for BTCMesh transport implementations.

    Concrete subclasses must implement all abstract methods and properties
    to provide a complete transport backend.

    Usage::

        transport = SomeConcreteTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(my_handler)
        transport.send("BTC_TX|abc12|1/3|deadbeef", "node_id_123")
        transport.disconnect()

    Or as a context manager::

        with SomeConcreteTransport() as transport:
            transport.connect("/dev/ttyUSB0")
            transport.set_message_handler(my_handler)
            transport.send("hello", "node_id_123")
    """

    @abstractmethod
    def connect(self, device_path: Optional[str] = None) -> None:
        """Connect to a device.

        Args:
            device_path: Specific device path (e.g., '/dev/ttyUSB0').
                         If None, the implementation should auto-detect.

        Raises:
            TransportConnectionError: If connection fails.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the device.

        Safe to call even if not currently connected (no-op in that case).
        After disconnect, is_connected must return False and
        local_node_id must return None.
        """
        ...

    @abstractmethod
    def send(self, message: str, destination: str) -> None:
        """Send a text message to a destination node.

        Args:
            message: The text message to send.
            destination: The destination node identifier (format depends on transport).

        Raises:
            TransportSendError: If the send operation fails.
            TransportConnectionError: If not currently connected.
        """
        ...

    @abstractmethod
    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register a callback for incoming text messages.

        Only one handler is active at a time. Calling this again
        replaces the previous handler.

        The handler receives (message_text, sender_id) where:
        - message_text is the decoded text content of the message
        - sender_id is the sender's node identifier (format depends on transport)

        Args:
            handler: Callback function(message_text, sender_id).
        """
        ...

    @abstractmethod
    def remove_message_handler(self) -> None:
        """Remove the current message handler.

        Safe to call even if no handler is currently set (no-op).
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the transport is currently connected to a device."""
        ...

    @property
    @abstractmethod
    def local_node_id(self) -> Optional[str]:
        """The local node identifier, or None if not connected."""
        ...

    # --- Context manager support (default implementation) ---

    def __enter__(self) -> BaseTransport:
        """Enter context manager. Does NOT auto-connect."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager. Disconnects if connected."""
        self.disconnect()
