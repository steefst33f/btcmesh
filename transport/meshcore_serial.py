"""Concrete transport implementation using MeshCore serial (USB) interface.

Wraps the asyncio-native `meshcore` Python client library into the
synchronous BaseTransport API. A dedicated background thread runs the
client's asyncio event loop for the lifetime of the connection; every
call that needs to `await` something bridges into that loop via
`_run_coro()` (a thin wrapper over `asyncio.run_coroutine_threadsafe()`)
bounded by an explicit timeout, mirroring the "bounded wait on a
background worker" shape MeshtasticSerialTransport.send() already uses
for the same reason (Issue 21 - never block the caller forever on a
wedged device). Calls that don't need to await anything (e.g.
`meshcore.MeshCore.subscribe()`, a plain synchronous list-append under
the hood) can be called directly, from any thread, with no bridge at
all - `_run_coro()` exists for awaiting, not as a blanket rule about
touching `self._mc`. Issue 52: never call `_run_coro()`-bridged methods
synchronously from inside code that is itself already running on
`self._loop`'s own thread (e.g. from within the CONTACT_MSG_RECV
callback) - that thread would be blocked waiting on a result only it
can produce, deadlocking for the full timeout every time.
"""
from __future__ import annotations

import asyncio
import logging
import queue
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
        self._my_node_name: Optional[str] = None
        self._subscription: Any = None
        self._dispatch_thread: Optional[threading.Thread] = None
        self._dispatch_queue: Optional["queue.Queue"] = None

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
        self._my_node_name = (mc.self_info or {}).get("name") or None

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
        self._my_node_name = None

        # Tear down the background loop/thread too - otherwise repeated
        # connect()/disconnect() cycles (e.g. DeviceWatchdog recovery
        # retries) would each leak a running event-loop thread instead of
        # replacing it on the next connect()'s _ensure_loop() call.
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            # call_soon_threadsafe() wakes the loop's selector, so
            # run_forever() reliably returns even with the just-abandoned
            # _mc.disconnect() coroutine above still pending (Issue 53) -
            # this join is a low-probability-timeout safety net, not the
            # primary bound. It matters because loop.close() raises
            # RuntimeError ("Cannot close a running event loop") if the
            # loop thread is still actually running - disconnect() must
            # never raise (see docstring), so skip close() in that case
            # rather than let it happen unguarded.
            if self._loop_thread is not None:
                self._loop_thread.join(timeout=self._SEND_TIMEOUT_SECONDS)
                still_running = self._loop_thread.is_alive()
            else:
                still_running = False
            if still_running:
                logger.warning(
                    "MeshCore event loop thread did not stop within %ss - "
                    "abandoning it without closing the loop",
                    self._SEND_TIMEOUT_SECONDS,
                )
            else:
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
        """Serial ports to try reconnecting to, for DeviceWatchdog's
        post-power-cycle recovery. Reuses
        core.device_scan.scan_serial_devices_detailed() (the stable-
        identity-aware scan, mirroring Story 26.3's Meshtastic version -
        candidate-port enumeration has nothing MeshCore-specific about it,
        so it's shared with MeshtasticSerialTransport's equivalent
        method), returning just the paths - identity verification against
        the expected device happens in DeviceWatchdog via local_node_id,
        not here.

        Excludes any Story 26.7 relay board's own control port via
        probe_relay_board_id() - the same guard MeshtasticSerialTransport's
        equivalent method uses (Issue 37/Issue 48): without it,
        DeviceWatchdog._try_candidate() (transport-agnostic by design, so
        it has no way to know about relay boards itself) would send the
        relay board a full MeshCore connect attempt during recovery.
        """
        from core.device_scan import scan_serial_devices_detailed
        from transport.power_control import probe_relay_board_id

        return [
            d.path
            for d in scan_serial_devices_detailed()
            if probe_relay_board_id(d.path) is None
        ]

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

    @property
    def local_node_name(self) -> Optional[str]:
        """The local device's configured name (from self_info["name"] at
        connect time), or None if not connected or the device has no name
        configured."""
        return self._my_node_name

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

    def _ensure_dispatch_thread(self) -> None:
        """Start the single background thread that invokes self._handler,
        decoupled from the asyncio loop thread (Issue 52).

        _on_event runs on self._loop's own thread (that's how the
        meshcore library invokes every subscriber). Calling the handler
        inline there deadlocked the moment the handler called back into
        any _run_coro()-bridged method - e.g. send(), to ACK the message
        it just received: _run_coro() needs that same loop thread to
        schedule new work, but it's already blocked running the handler,
        so it can never get back around to running what it just
        scheduled. Confirmed via real hardware: send() called from within
        the receive handler took exactly _SEND_TIMEOUT_SECONDS (10.00s)
        before raising, every time, independent of routing/path state -
        a same-thread reentrancy deadlock, not a network delay.

        One dedicated worker thread, fed by a queue, keeps message
        handling serialized (matching this protocol's stop-and-wait
        shape - the community meshcore-mqtt bridge project applies the
        same "decouple receive from handling" principle via an
        asyncio.Queue, though in its fully-async architecture it never
        needs the thread-bridging BaseTransport's synchronous contract
        requires here) while freeing the loop thread immediately, so a
        handler-triggered send() can actually run."""
        if self._dispatch_thread is not None:
            return
        self._dispatch_queue = queue.Queue()

        def _worker() -> None:
            while True:
                item = self._dispatch_queue.get()
                if item is None:  # sentinel: shut down
                    return
                text, sender = item
                try:
                    self._handler(text, sender)
                except Exception:
                    logger.exception("Error in message handler")

        self._dispatch_thread = threading.Thread(target=_worker, daemon=True)
        self._dispatch_thread.start()

    def _stop_dispatch_thread(self) -> None:
        """Stop the dispatch thread started by _ensure_dispatch_thread()."""
        if self._dispatch_thread is None:
            return
        self._dispatch_queue.put(None)  # sentinel
        self._dispatch_thread.join(timeout=self._SEND_TIMEOUT_SECONDS)
        self._dispatch_thread = None
        self._dispatch_queue = None

    def _subscribe(self) -> None:
        """Subscribe to MeshCore contact-message events, and actively start
        pulling any queued ones (Issue 50).

        MeshCore's companion protocol doesn't push received messages
        proactively - it sends a MESSAGES_WAITING ping and expects the
        client to explicitly pull each message via get_msg(); only that
        pull's reply becomes a CONTACT_MSG_RECV event.
        start_auto_message_fetching() does exactly this pull automatically
        (once immediately, to catch anything already queued, then again on
        every future MESSAGES_WAITING event) - without it, CONTACT_MSG_RECV
        never fires for a real incoming message, even though it physically
        reaches the radio (confirmed via real hardware: RX_LOG_DATA and
        MESSAGES_WAITING fired, CONTACT_MSG_RECV never did)."""
        from meshcore import EventType

        self._ensure_dispatch_thread()

        async def _on_event(event) -> None:
            data = event.payload or {}
            text = data.get("text")
            sender = data.get("pubkey_prefix")
            # Missing text isn't necessarily malformed data - CONTACT_MSG_RECV
            # also fires for non-text payload types (e.g. binary/command
            # data) that this transport doesn't handle, so this is routine
            # filtering, not an error worth logging. Missing sender would be
            # a genuine anomaly (this event is specifically for private/
            # direct messages, not the separate CHANNEL_MSG_RECV this
            # transport never subscribes to, so pubkey_prefix should always
            # be present) - checked anyway since the handler is useless
            # without knowing who to reply to.
            if not text or not sender or self._handler is None:
                return
            self._dispatch_queue.put((text, sender))

        self._subscription = self._mc.subscribe(EventType.CONTACT_MSG_RECV, _on_event)
        self._run_coro(
            self._mc.start_auto_message_fetching(), self._SEND_TIMEOUT_SECONDS
        )

    def _unsubscribe(self) -> None:
        """Unsubscribe from MeshCore contact-message events and stop the
        active message-pulling started by _subscribe() (Issue 50), and the
        dispatch thread that invokes the handler (Issue 52)."""
        try:
            if self._subscription is not None:
                self._subscription.unsubscribe()
        except Exception:
            pass
        self._subscription = None
        self._stop_dispatch_thread()
        try:
            self._run_coro(
                self._mc.stop_auto_message_fetching(), self._SEND_TIMEOUT_SECONDS
            )
        except Exception:
            pass

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
