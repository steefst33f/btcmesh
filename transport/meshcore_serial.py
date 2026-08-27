"""Concrete transport implementation using MeshCore serial (USB) interface.

Wraps the asyncio-native `meshcore` Python client library into the
synchronous BaseTransport API. A dedicated background thread runs the
client's asyncio event loop for the lifetime of the connection; every
public method bridges into it via `asyncio.run_coroutine_threadsafe()`
bounded by an explicit timeout, mirroring the "bounded wait on a
background worker" shape MeshtasticSerialTransport.send() already uses
for the same reason (Issue 21 - never block the caller forever on a
wedged device).
"""
from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, List, Optional

from core.constants import MESHCORE_MAX_CHUNK_SIZE
from core.protocol import is_valid_hex
from transport.base import (
    BaseTransport,
    MessageHandler,
    TransportConnectionError,
    TransportSendError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MeshCore serial transport
# ---------------------------------------------------------------------------


class MeshCoreSerialTransport(BaseTransport):
    """Transport backend using a MeshCore companion device over USB serial.

    Wraps the `meshcore` library's asyncio client (`meshcore.MeshCore`) and
    its event-subscription mechanism into the synchronous BaseTransport API.

    Usage::

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")  # or None for auto-detect
        transport.set_message_handler(my_handler)
        transport.send("hello", "a1b2c3d4e5f6")
        transport.disconnect()
    """

    _BAUD_RATE: int = 115200
    _CONNECT_TIMEOUT_SECONDS: float = 15.0
    _SEND_TIMEOUT_SECONDS: float = 10.0
    _CHECK_ALIVE_TIMEOUT_SECONDS: float = 20.0
    # MeshCore addresses contacts by a 6-byte public-key prefix (12 hex
    # chars) throughout its protocol and companion apps - incoming
    # messages report the sender this way (see _on_event below), so
    # local_node_id uses the same granularity for consistent display,
    # even though the device's full public key (32 bytes) is available.
    _PUBKEY_PREFIX_BYTES: int = 6

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._mc: Any = None
        self._handler: Optional[MessageHandler] = None
        self._my_public_key: Optional[str] = None
        self._subscription: Any = None

    # --- BaseTransport implementation ---

    def connect(self, device_path: Optional[str] = None) -> None:
        """Connect to a MeshCore device via serial.

        Args:
            device_path: Serial port path (e.g., '/dev/ttyUSB0'). If None,
                         auto-detects only when exactly one serial port is
                         present (unlike Meshtastic, the `meshcore` library
                         itself has no device-discovery/auto-detect of its
                         own - `create_serial()` requires an explicit port).

        Raises:
            TransportConnectionError: If connection fails.
        """
        if self._mc is not None:
            raise TransportConnectionError("Already connected")

        try:
            from meshcore import MeshCore
        except ImportError as exc:
            raise TransportConnectionError(
                "meshcore library not installed. "
                "Install it with: pip install meshcore"
            ) from exc

        port = device_path or self._autodetect_port()

        self._ensure_loop()

        async def _do_connect():
            return await MeshCore.create_serial(port, self._BAUD_RATE)

        try:
            mc = self._run_coro(_do_connect(), self._CONNECT_TIMEOUT_SECONDS)
        except Exception as exc:
            raise TransportConnectionError(f"Failed to connect: {exc}") from exc

        # create_serial() returns None (rather than raising) when the
        # underlying connect()/send_appstart() handshake fails.
        if mc is None:
            raise TransportConnectionError(
                f"Failed to connect to MeshCore device at {port}"
            )

        public_key = (mc.self_info or {}).get("public_key")
        if not public_key:
            try:
                self._run_coro(mc.disconnect(), self._SEND_TIMEOUT_SECONDS)
            except Exception:
                pass
            raise TransportConnectionError(
                "Connected but could not retrieve device info"
            )

        self._mc = mc
        self._my_public_key = public_key

        # If handler was set before connect, start listening now
        if self._handler is not None:
            self._subscribe()

        logger.info("Connected to MeshCore device. Public key: %s", self.local_node_id)

    def disconnect(self) -> None:
        """Disconnect from the MeshCore device.

        Safe to call even if not currently connected.
        Does NOT clear the message handler (preserved for reconnect).
        """
        if self._subscription is not None:
            self._unsubscribe()

        if self._mc is not None:
            try:
                self._run_coro(self._mc.disconnect(), self._SEND_TIMEOUT_SECONDS)
            except Exception:
                pass
            self._mc = None

        self._my_public_key = None

        # Tear down the background loop/thread too - otherwise repeated
        # connect()/disconnect() cycles (e.g. DeviceWatchdog recovery
        # retries) would each leak a running event-loop thread instead of
        # replacing it on the next connect()'s _ensure_loop() call.
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=self._SEND_TIMEOUT_SECONDS)
            self._loop.close()
            self._loop = None
            self._loop_thread = None

    def send(self, message: str, destination: str) -> None:
        """Send a text message to a destination contact.

        Args:
            message: The text message to send.
            destination: The destination contact's MeshCore public key
                (full hex string or 6-byte prefix).

        Raises:
            TransportConnectionError: If not connected.
            TransportSendError: If the send operation fails, including
                if it doesn't complete within _SEND_TIMEOUT_SECONDS (same
                wedge protection as MeshtasticSerialTransport.send(), see
                Issue 21).
        """
        if self._mc is None:
            raise TransportConnectionError("Not connected")

        async def _do_send():
            return await self._mc.commands.send_msg(destination, message)

        try:
            result = self._run_coro(_do_send(), self._SEND_TIMEOUT_SECONDS)
        except FutureTimeoutError as exc:
            raise TransportSendError(
                f"Send timed out after {self._SEND_TIMEOUT_SECONDS}s - "
                "device may be unresponsive"
            ) from exc
        except Exception as exc:
            raise TransportSendError(f"Failed to send message: {exc}") from exc

        from meshcore import EventType

        if result is None or result.type == EventType.ERROR:
            raise TransportSendError(
                f"Failed to send message: {getattr(result, 'payload', None)}"
            )

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register a callback for incoming text messages.

        Only one handler is active at a time. Calling this again
        replaces the previous handler. The handler can be set before
        or after connect - subscription is deferred until connected.

        Args:
            handler: Callback function(message_text, sender_id).
        """
        if self._subscription is not None:
            self._unsubscribe()

        self._handler = handler

        if self._mc is not None:
            self._subscribe()

    def remove_message_handler(self) -> None:
        """Remove the current message handler.

        Safe to call even if no handler is currently set.
        """
        if self._subscription is not None:
            self._unsubscribe()
        self._handler = None

    def check_alive(self, timeout_seconds: Optional[float] = None) -> bool:
        """Best-effort liveness check. Returns False (never raises) if not
        connected or the device doesn't respond within timeout_seconds
        (falls back to _CHECK_ALIVE_TIMEOUT_SECONDS when omitted).

        Sends MeshCore's lightweight device-query command and waits for a
        real round-trip DEVICE_INFO response.
        """
        if self._mc is None:
            return False
        try:
            from meshcore import EventType

            effective_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else self._CHECK_ALIVE_TIMEOUT_SECONDS
            )
            result = self._run_coro(
                self._mc.commands.send_device_query(), effective_timeout
            )
            return result is not None and result.type != EventType.ERROR
        except Exception:
            return False

    def validate_destination(self, destination: str) -> None:
        """Validate a MeshCore destination's structural format: a
        hex-encoded public key or public-key prefix (Story 30.2).

        Raises:
            ValueError: If destination is empty, contains non-hex
                characters, or has odd length (a public key/prefix is
                always a whole number of bytes).
        """
        if not destination:
            raise ValueError("Destination cannot be empty")
        if not is_valid_hex(destination) or len(destination) % 2 != 0:
            raise ValueError(
                "Destination must be a hex-encoded public key or prefix"
            )

    def scan_for_reconnect_candidates(self) -> List[str]:
        """Not yet implemented for MeshCore - returns an empty list.

        MeshCore device scanning/identity probing (the equivalent of
        core/meshtastic_utils.py) is separate, deferred work (Story 30.4).
        BaseTransport's contract explicitly allows an empty list here
        rather than requiring every transport to support discovery.
        """
        return []

    @property
    def max_chunk_size(self) -> int:
        """Maximum hex-character payload size per chunk (Issue 51) - well
        under MeshCore's own MAX_TEXT_LEN cap once wire-format overhead is
        accounted for; see core.constants.MESHCORE_MAX_CHUNK_SIZE."""
        return MESHCORE_MAX_CHUNK_SIZE

    @property
    def is_connected(self) -> bool:
        """Whether the transport is currently connected."""
        return self._mc is not None

    @property
    def local_node_id(self) -> Optional[str]:
        """The local MeshCore public-key prefix (12 hex chars), or None."""
        if self._my_public_key is None:
            return None
        return self._my_public_key[: self._PUBKEY_PREFIX_BYTES * 2]

    # --- Internal helpers ---

    def _ensure_loop(self) -> None:
        """Start the background asyncio event loop thread if not already
        running. Kept alive for the transport's connected lifetime so a
        persistent event subscription (incoming messages) and repeated
        send()/check_alive() calls can all share one asyncio client."""
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._loop_thread.start()

    def _run_coro(self, coro, timeout: float):
        """Submit a coroutine to the background loop and block the calling
        thread for its result, bounded by `timeout`."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def _subscribe(self) -> None:
        """Subscribe to MeshCore contact-message events."""
        from meshcore import EventType

        async def _on_event(event) -> None:
            data = event.payload or {}
            text = data.get("text")
            sender = data.get("pubkey_prefix")
            if not text or self._handler is None:
                return
            try:
                self._handler(text, sender)
            except Exception:
                logger.exception("Error in message handler")

        self._subscription = self._mc.subscribe(EventType.CONTACT_MSG_RECV, _on_event)

    def _unsubscribe(self) -> None:
        """Unsubscribe from MeshCore contact-message events."""
        try:
            if self._subscription is not None:
                self._subscription.unsubscribe()
        except Exception:
            pass
        self._subscription = None

    @staticmethod
    def _autodetect_port() -> str:
        """Auto-detect a serial port when none is given. Unlike Meshtastic
        (which has its own multi-candidate-aware auto-detect), the
        `meshcore` library's create_serial() always requires an explicit
        port, so BTCMesh does its own single-candidate detection here."""
        from serial.tools import list_ports

        candidates = [p.device for p in list_ports.comports()]
        if not candidates:
            raise TransportConnectionError("No serial devices found")
        if len(candidates) > 1:
            raise TransportConnectionError(
                "Multiple serial devices detected - please select a "
                "specific device instead of auto-detect"
            )
        return candidates[0]
