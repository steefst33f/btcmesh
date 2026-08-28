"""Concrete transport implementation using Meshtastic serial (USB) interface.

Wraps the meshtastic.serial_interface.SerialInterface and the pubsub
message-receive mechanism into the BaseTransport API.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, List, Optional

from core.constants import DEFAULT_CHUNK_SIZE
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
    _SEND_TIMEOUT_SECONDS: float = 10.0
    # A generous bound over sendText()'s normal near-instant completion
    # (see project/plans/story_26_2.md - raw writes return in ~0ms even
    # against a wedged device in the common case), while far short of the
    # multi-minute hang documented in Issue 21 - a genuinely wedged/stalled
    # device froze the entire client GUI, with no way to time out or abort
    # the underlying blocked call.
    _CHECK_ALIVE_TIMEOUT_SECONDS: float = 20.0
    # check_alive()'s own explicit bound (Issue 46) - the interface's
    # SerialInterface/MeshInterface is constructed with no explicit
    # `timeout=`, so it silently inherits the meshtastic library's own
    # 300-second default reply-wait. Using self._iface.waitForAckNak()
    # directly would block check_alive() for up to 5 minutes against a
    # genuinely dead device - real-hardware confirmed via `sudo py-spy
    # dump` mid-stall (see Issue 46's write-up). check_alive() instead
    # builds its own short-lived Timeout below, scoped to just this one
    # probe, without touching the interface's other reply-wait behavior.

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
            # connectNow=False: open the serial port but don't perform the
            # handshake yet. meshtastic's SerialInterface otherwise does the
            # handshake inside its own constructor, so if it fails partway
            # through (e.g. a timeout waiting for the device's config), the
            # assignment to `iface` never completes and we have no reference
            # to close the already-opened port/reader thread - leaking an
            # exclusive OS-level lock on the port for the rest of the process
            # lifetime. Doing the handshake ourselves below keeps `iface`
            # reachable so we can clean it up on failure.
            if device_path:
                iface = meshtastic.serial_interface.SerialInterface(
                    devPath=device_path, connectNow=False
                )
            else:
                # Auto-detect device if no path provided
                iface = meshtastic.serial_interface.SerialInterface(connectNow=False)
        except SystemExit as exc:
            # meshtastic.util.findPorts()-based auto-detect (devPath=None)
            # calls meshtastic.util.our_exit() - print() + sys.exit() -
            # when more than one candidate serial port is found, rather
            # than raising a catchable exception. SystemExit is a
            # BaseException, not an Exception, so it would otherwise skip
            # the `except Exception` below entirely and silently kill
            # whatever thread called connect() (Issue 41). Only reachable
            # from the auto-detect branch above.
            raise TransportConnectionError(
                "Multiple Meshtastic devices detected - please select a "
                "specific device instead of Auto-detect"
            ) from exc
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

        try:
            iface.connect()
            if not iface.noProto:
                iface.waitForConfig()
        except Exception as exc:
            try:
                iface.close()
            except Exception:
                pass
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

        Safe to call even if not currently connected - never raises,
        including if close() itself hangs (Issue 53: a device with a
        backed-up outgoing queue can make the meshtastic library's
        iface.close() block indefinitely; bounded the same way send()
        already is - Issue 21 - since every real caller of disconnect()
        treats it as safe-to-call with no exception handling of its own,
        e.g. DeviceWatchdog._recover_once()).
        Does NOT clear the message handler (preserved for reconnect).
        """
        if self._subscribed:
            self._unsubscribe()

        if self._iface is not None:
            iface = self._iface
            outcome: dict = {}

            def _do_close() -> None:
                try:
                    iface.close()
                except Exception as exc:
                    outcome["error"] = exc

            worker = threading.Thread(target=_do_close, daemon=True)
            worker.start()
            worker.join(timeout=self._SEND_TIMEOUT_SECONDS)

            if worker.is_alive():
                # Can't forcibly stop the underlying blocked call - it's
                # abandoned, not killed, same as send()'s worker thread.
                # disconnect() must never raise (see docstring), so just
                # log and move on to the state cleanup below.
                logger.warning(
                    "iface.close() did not return within %ss - device may "
                    "be unresponsive; abandoning the close and continuing",
                    self._SEND_TIMEOUT_SECONDS,
                )
            elif "error" in outcome:
                logger.warning("iface.close() raised: %s", outcome["error"])

            self._iface = None

        self._my_node_num = None

    def send(self, message: str, destination: str) -> None:
        """Send a text message to a destination node.

        Args:
            message: The text message to send.
            destination: The destination node ID (e.g., '!deadbeef').

        Raises:
            TransportConnectionError: If not connected.
            TransportSendError: If the send operation fails, including
                if it doesn't complete within _SEND_TIMEOUT_SECONDS (see
                Issue 21 - a wedged device caused this call to block
                indefinitely, freezing the entire client GUI with no way
                to time out or abort it).
        """
        if self._iface is None:
            raise TransportConnectionError("Not connected")

        outcome: dict = {}

        def _do_send() -> None:
            try:
                self._iface.sendText(
                    text=message,
                    destinationId=destination,
                    wantAck=self._WANT_ACK,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=_do_send, daemon=True)
        worker.start()
        worker.join(timeout=self._SEND_TIMEOUT_SECONDS)

        if worker.is_alive():
            # Can't forcibly stop the underlying blocked call - it's
            # abandoned, not killed. This still fixes the actual bug:
            # the caller (a retry loop, an abort flag, a GUI thread) is
            # no longer held hostage by it forever.
            raise TransportSendError(
                f"Send timed out after {self._SEND_TIMEOUT_SECONDS}s - "
                "device may be unresponsive"
            )
        if "error" in outcome:
            raise TransportSendError(
                f"Failed to send message: {outcome['error']}"
            ) from outcome["error"]

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

    def check_alive(self, timeout_seconds: Optional[float] = None) -> bool:
        """Best-effort liveness check. Returns False (never raises) if not
        connected or the device doesn't respond within timeout_seconds
        (falls back to _CHECK_ALIVE_TIMEOUT_SECONDS, ~20s, when omitted).

        Sends a local admin "get device metadata" request and waits for a
        real round-trip acknowledgment - proven by real hardware testing
        (see project/plans/story_26_2.md) to be the only reliable signal:
        getMyNodeInfo() only reads an in-memory cache, and sendHeartbeat()/
        raw writes return successfully even against a genuinely wedged
        device, since the OS buffers the write regardless of whether
        firmware actually processes it.

        Deliberately reimplements node.Node.getMetadata() rather than
        calling it directly: its response handler unconditionally prints
        firmware/hardware info to stdout, which we don't want firing from a
        periodic background health check, and globally redirecting stdout
        around the call would be unsafe once this runs on a background
        watchdog thread (Story 26.4) alongside other console/log output.

        Waits via its own short-lived Timeout rather than
        self._iface.waitForAckNak() - the interface's own wait uses
        self._iface._timeout, built from SerialInterface's default
        300-second reply timeout (never overridden by connect()), which
        would let a single check block for up to 5 minutes against a
        genuinely dead device instead of the ~20s this method documents
        (Issue 46, confirmed via real-hardware `py-spy dump`).
        """
        if self._iface is None:
            return False
        try:
            from meshtastic import admin_pb2
            from meshtastic.mesh_interface import Timeout

            def _quiet_response_handler(p):
                if "routing" in p["decoded"]:
                    if p["decoded"]["routing"]["errorReason"] != "NONE":
                        self._iface._acknowledgment.receivedNak = True
                else:
                    self._iface._acknowledgment.receivedAck = True

            p = admin_pb2.AdminMessage()
            p.get_device_metadata_request = True
            self._iface.localNode._sendAdmin(
                p, wantResponse=True, onResponse=_quiet_response_handler
            )
            effective_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else self._CHECK_ALIVE_TIMEOUT_SECONDS
            )
            return Timeout(maxSecs=effective_timeout).waitForAckNak(
                self._iface._acknowledgment
            )
        except Exception:
            return False

    def validate_destination(self, destination: str) -> None:
        """Validate a Meshtastic destination node ID's structural format
        (Issue 30 / Story 30.2 - moved here from core/protocol.py verbatim,
        no behavior change).

        Raises:
            ValueError: If destination is empty or doesn't start with '!'.
        """
        if not destination:
            raise ValueError("Destination cannot be empty")
        if not destination.startswith("!"):
            raise ValueError("Destination must start with '!'")

    def scan_for_reconnect_candidates(self) -> List[str]:
        """Serial ports to try reconnecting to, for DeviceWatchdog's
        post-power-cycle recovery. Reuses
        core.device_scan.scan_serial_devices_detailed() (the
        stable-identity-aware scan from Story 26.3 - candidate-port
        enumeration has nothing Meshtastic-specific about it, so it's
        shared with MeshCoreSerialTransport's equivalent method), returning
        just the paths - identity verification against the expected device
        happens in DeviceWatchdog via local_node_id, not here.

        Excludes any Story 26.7 relay board's own control port via
        probe_relay_board_id() - the same guard Issue 37 already put in
        front of every other direct transport.connect() call site.
        Without it, DeviceWatchdog._try_candidate() (transport-agnostic
        by design, so it has no way to know about relay boards itself)
        sends the relay board a full Meshtastic handshake during
        recovery, corrupting its serial buffer and breaking the very
        next power_control.power_cycle() call (Issue 48, confirmed via
        real-hardware test - reproduced twice in a row before this fix).
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
        """Maximum hex-character payload size per chunk (Issue 51)."""
        return DEFAULT_CHUNK_SIZE

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

        Filters for TEXT_MESSAGE_APP, excludes self-messages and messages
        not explicitly addressed to this node, extracts text and sender ID,
        then invokes the registered handler.
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

        # Filter: messages not explicitly addressed to this node. Real
        # Meshtastic DM packets always carry a destination (even broadcasts
        # use an explicit broadcast address rather than omitting it), so
        # missing destination info means this isn't a direct message to us -
        # drop broadcasts, messages meant for another node, and anything
        # with no destination info at all.
        dest_num = packet.get("to")
        if dest_num is None:
            dest_id = packet.get("toId")
            if dest_id is None:
                return
            if dest_id != self._format_node_id(self._my_node_num):
                return
        elif dest_num != self._my_node_num:
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
