"""Concrete transport implementation using Meshtastic serial (USB) interface.

Wraps the meshtastic.serial_interface.SerialInterface and the pubsub
message-receive mechanism into the BaseTransport API.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from transport.base import (
    BaseTransport,
    MessageHandler,
    TransportConnectionError,
    TransportSendError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Meshtastic serial transport
# ---------------------------------------------------------------------------


class MeshtasticSerialTransport(BaseTransport):
    """Transport backend using Meshtastic serial (USB) connection.

    Wraps SerialInterface for connecting/sending and pubsub for receiving.
    Self-messages are filtered out before reaching the handler.

    Usage::

        transport = MeshtasticSerialTransport()
        transport.connect("/dev/ttyUSB0")  # or None for auto-detect
        transport.set_message_handler(my_handler)
        transport.send("hello", "!deadbeef")
        transport.disconnect()
    """

    _WANT_ACK: bool = False
    _RECEIVE_TOPIC: str = "meshtastic.receive"

    def __init__(self) -> None:
        self._iface: Any = None
        self._handler: Optional[MessageHandler] = None
        self._my_node_num: Optional[int] = None
        self._subscribed: bool = False

    # --- BaseTransport implementation ---

    def connect(self, device_path: Optional[str] = None) -> None:
        """Connect to a Meshtastic device via serial.

        Args:
            device_path: Serial port path (e.g., '/dev/ttyUSB0').
                         If None, the meshtastic library will auto-detect.

        Raises:
            TransportConnectionError: If connection fails.
        """
        if self._iface is not None:
            raise TransportConnectionError("Already connected")

        try:
            import meshtastic.serial_interface
        except ImportError:
            raise TransportConnectionError(
                "meshtastic library not installed. "
                "Install it with: pip install meshtastic"
            )

        try:
            if device_path:
                iface = meshtastic.serial_interface.SerialInterface(
                    devPath=device_path
                )
            else:
                # Auto-detect device if no path provided
                iface = meshtastic.serial_interface.SerialInterface()
        except Exception as exc:
            err_type = type(exc).__name__
            if (
                err_type == "NoDeviceError"
                or "No Meshtastic device found" in str(exc)
            ):
                raise TransportConnectionError(
                    "No Meshtastic device found"
                ) from exc
            raise TransportConnectionError(
                f"Failed to connect: {exc}"
            ) from exc

        # Validate device info
        my_node_num = None
        if (
            hasattr(iface, "myInfo")
            and iface.myInfo
            and hasattr(iface.myInfo, "my_node_num")
        ):
            my_node_num = iface.myInfo.my_node_num

        # cleanup connection if we can't get the node number 
        # (which is essential for filtering self-messages)
        if my_node_num is None:
            try:
                iface.close()
            except Exception:
                pass
            raise TransportConnectionError(
                "Connected but could not retrieve device info"
            )

        self._iface = iface
        self._my_node_num = my_node_num

        # If handler was set before connect, start listening now
        if self._handler is not None and not self._subscribed:
            self._subscribe()

        logger.info(
            "Connected to Meshtastic device. Node ID: %s",
            self._format_node_id(my_node_num),
        )

    def disconnect(self) -> None:
        """Disconnect from the Meshtastic device.

        Safe to call even if not currently connected.
        Does NOT clear the message handler (preserved for reconnect).
        """
        if self._subscribed:
            self._unsubscribe()

        if self._iface is not None:
            try:
                self._iface.close()
            except Exception:
                pass
            self._iface = None

        self._my_node_num = None

    def send(self, message: str, destination: str) -> None:
        """Send a text message to a destination node.

        Args:
            message: The text message to send.
            destination: The destination node ID (e.g., '!deadbeef').

        Raises:
            TransportConnectionError: If not connected.
            TransportSendError: If the send operation fails.
        """
        if self._iface is None:
            raise TransportConnectionError("Not connected")

        try:
            self._iface.sendText(
                text=message,
                destinationId=destination,
                wantAck=self._WANT_ACK,
            )
        except Exception as exc:
            raise TransportSendError(
                f"Failed to send message: {exc}"
            ) from exc

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register a callback for incoming text messages.

        Only one handler is active at a time. Calling this again
        replaces the previous handler. The handler can be set before
        or after connect — subscription is deferred until connected.

        Args:
            handler: Callback function(message_text, sender_id).
        """
        if self._subscribed:
            self._unsubscribe()

        self._handler = handler

        if self._iface is not None:
            self._subscribe()

    def remove_message_handler(self) -> None:
        """Remove the current message handler.

        Safe to call even if no handler is currently set.
        """
        if self._subscribed:
            self._unsubscribe()
        self._handler = None

    @property
    def is_connected(self) -> bool:
        """Whether the transport is currently connected."""
        return self._iface is not None

    @property
    def local_node_id(self) -> Optional[str]:
        """The local Meshtastic node ID (e.g., '!deadbeef'), or None."""
        if self._my_node_num is None:
            return None
        return self._format_node_id(self._my_node_num)

    # --- Internal helpers ---

    def _subscribe(self) -> None:
        """Subscribe to Meshtastic receive events via pubsub."""
        from pubsub import pub

        pub.subscribe(self._on_meshtastic_receive, self._RECEIVE_TOPIC)
        self._subscribed = True

    def _unsubscribe(self) -> None:
        """Unsubscribe from Meshtastic receive events."""
        try:
            from pubsub import pub

            pub.unsubscribe(self._on_meshtastic_receive, self._RECEIVE_TOPIC)
        except Exception:
            pass
        self._subscribed = False

    def _on_meshtastic_receive(
        self, packet: dict, interface: Any = None, **kwargs: Any
    ) -> None:
        """Internal pubsub callback for received Meshtastic packets.

        Filters for TEXT_MESSAGE_APP, excludes self-messages, extracts
        text and sender ID, then invokes the registered handler.
        """
        if self._handler is None:
            return

        decoded = packet.get("decoded")
        if not decoded:
            return

        # Filter: TEXT_MESSAGE_APP only
        if str(decoded.get("portnum")) != "TEXT_MESSAGE_APP":
            return

        # Filter: self-messages
        sender_num = packet.get("from")
        if sender_num is not None and sender_num == self._my_node_num:
            return

        # Extract message text
        message_text = self._extract_text_from_packet(decoded)
        if not message_text:
            return

        # Format sender ID
        sender_id = packet.get("fromId")
        if sender_id is None and sender_num is not None:
            sender_id = self._format_node_id(sender_num)
        if sender_id is None:
            sender_id = "!00000000"

        try:
            self._handler(message_text, sender_id)
        except Exception:
            logger.exception("Error in message handler")

    @staticmethod
    def _format_node_id(node_num: int) -> str:
        """Format an integer node number as a Meshtastic node ID string.

        Uses zero-padded 8-character hex: ``!deadbeef``.
        """
        return f"!{node_num:08x}"

    @staticmethod
    def _extract_text_from_packet(decoded: dict) -> Optional[str]:
        """Extract text content from a decoded Meshtastic packet.

        Supports both the ``text`` field and ``payload`` bytes fallback.
        """
        text = decoded.get("text")
        if text:
            return text
        payload = decoded.get("payload")
        if payload is not None:
            try:
                return payload.decode("utf-8") or None
            except (UnicodeDecodeError, AttributeError):
                return None
        return None
