"""Tests for transport/meshcore_serial.py — MeshCoreSerialTransport implementation.

Tests verify:
- Connection lifecycle (connect, disconnect, reconnect)
- Message sending with proper arguments
- Message receiving via the event-subscription callback
- Error handling for various failure modes
- Handler management and subscription lifecycle
- Liveness checking (check_alive)
"""
import asyncio
import sys
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from transport.base import (
    TransportConnectionError,
    TransportSendError,
)
from transport.meshcore_serial import MeshCoreSerialTransport


# ---------------------------------------------------------------------------
# Helpers: Mock meshcore objects
# ---------------------------------------------------------------------------


class FakeEventType:
    """Stand-in for meshcore.EventType - a real Enum isn't needed, only
    identity/equality across the values the transport checks."""
    CONTACT_MSG_RECV = "contact_message"
    ERROR = "command_error"
    MSG_SENT = "message_sent"
    DEVICE_INFO = "device_info"


class FakeEvent:
    def __init__(self, type_, payload=None):
        self.type = type_
        self.payload = payload


class MockMeshCoreClient:
    """Mock for the meshcore.MeshCore async client instance."""

    def __init__(self, public_key="ab" * 32):
        self.self_info = {"public_key": public_key}
        self.commands = MagicMock()
        self.commands.send_msg = AsyncMock(
            return_value=FakeEvent(FakeEventType.MSG_SENT)
        )
        self.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.DEVICE_INFO)
        )
        self.disconnect = AsyncMock()
        self.subscribe = MagicMock(return_value=MagicMock())
        self.start_auto_message_fetching = AsyncMock(return_value=MagicMock())
        self.stop_auto_message_fetching = AsyncMock()


def _install_mock_meshcore(mock_client):
    """Install a fake `meshcore` module returning `mock_client` from
    MeshCore.create_serial(), plus the FakeEventType stand-in."""
    mock_module = MagicMock()
    mock_module.MeshCore.create_serial = AsyncMock(return_value=mock_client)
    mock_module.EventType = FakeEventType
    sys.modules['meshcore'] = mock_module
    return mock_module


def _uninstall_mock_meshcore():
    if 'meshcore' in sys.modules:
        del sys.modules['meshcore']


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportConnect(unittest.TestCase):
    """Tests for connect method."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_connect_with_explicit_device_path(self):
        mock_client = MockMeshCoreClient(public_key="aa11bb22cc33" + "00" * 26)
        mock_module = _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertTrue(transport.is_connected)
        self.assertEqual(transport.local_node_id, "aa11bb22cc33")
        mock_module.MeshCore.create_serial.assert_called_once_with(
            "/dev/ttyUSB0", MeshCoreSerialTransport._BAUD_RATE
        )
        transport.disconnect()

    def test_connect_auto_detects_single_serial_port(self):
        mock_client = MockMeshCoreClient()
        mock_module = _install_mock_meshcore(mock_client)

        fake_port = MagicMock()
        fake_port.device = "/dev/ttyUSB7"
        with patch(
            "serial.tools.list_ports.comports", return_value=[fake_port]
        ):
            transport = MeshCoreSerialTransport()
            transport.connect(None)

        self.assertTrue(transport.is_connected)
        mock_module.MeshCore.create_serial.assert_called_once_with(
            "/dev/ttyUSB7", MeshCoreSerialTransport._BAUD_RATE
        )
        transport.disconnect()

    def test_connect_raises_when_no_ports_for_auto_detect(self):
        _install_mock_meshcore(MockMeshCoreClient())
        with patch("serial.tools.list_ports.comports", return_value=[]):
            transport = MeshCoreSerialTransport()
            with self.assertRaises(TransportConnectionError) as ctx:
                transport.connect(None)
        self.assertIn("No serial devices found", str(ctx.exception))

    def test_connect_raises_when_multiple_ports_for_auto_detect(self):
        _install_mock_meshcore(MockMeshCoreClient())
        port_a, port_b = MagicMock(), MagicMock()
        port_a.device, port_b.device = "/dev/ttyUSB0", "/dev/ttyUSB1"
        with patch(
            "serial.tools.list_ports.comports", return_value=[port_a, port_b]
        ):
            transport = MeshCoreSerialTransport()
            with self.assertRaises(TransportConnectionError) as ctx:
                transport.connect(None)
        self.assertIn("Multiple serial devices detected", str(ctx.exception))

    def test_connect_raises_when_already_connected(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")
        self.assertIn("Already connected", str(ctx.exception))
        transport.disconnect()

    def test_connect_raises_when_meshcore_not_installed(self):
        # Setting a sys.modules entry to None forces any `import meshcore`/
        # `from meshcore import ...` to raise ImportError immediately, per
        # Python's import system - this simulates "library not installed"
        # reliably regardless of whether the real package happens to be
        # installed in the environment running this test.
        sys.modules['meshcore'] = None

        transport = MeshCoreSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")
        self.assertIn("not installed", str(ctx.exception))

    def test_connect_raises_when_create_serial_returns_none(self):
        mock_module = MagicMock()
        mock_module.MeshCore.create_serial = AsyncMock(return_value=None)
        mock_module.EventType = FakeEventType
        sys.modules['meshcore'] = mock_module

        transport = MeshCoreSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_connect_raises_on_generic_exception(self):
        mock_module = MagicMock()
        mock_module.MeshCore.create_serial = AsyncMock(
            side_effect=RuntimeError("port busy")
        )
        mock_module.EventType = FakeEventType
        sys.modules['meshcore'] = mock_module

        transport = MeshCoreSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_connect_raises_when_public_key_missing(self):
        mock_client = MockMeshCoreClient()
        mock_client.self_info = {}
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")
        self.assertIn("could not retrieve device info", str(ctx.exception))
        mock_client.disconnect.assert_awaited_once()


# ---------------------------------------------------------------------------
# Disconnect tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportDisconnect(unittest.TestCase):
    """Tests for disconnect method."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_disconnect_closes_connection(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        self.assertTrue(transport.is_connected)

        transport.disconnect()

        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport.local_node_id)
        mock_client.disconnect.assert_awaited_once()

    def test_disconnect_idempotent(self):
        transport = MeshCoreSerialTransport()
        transport.disconnect()  # Should not raise
        transport.disconnect()  # Should not raise

    def test_disconnect_handles_close_exception(self):
        mock_client = MockMeshCoreClient()
        mock_client.disconnect = AsyncMock(side_effect=RuntimeError("close failed"))
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.disconnect()  # Should not raise
        self.assertFalse(transport.is_connected)

    def test_disconnect_unsubscribes_handler(self):
        mock_client = MockMeshCoreClient()
        mock_subscription = MagicMock()
        mock_client.subscribe.return_value = mock_subscription
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda msg, sender: None)

        transport.disconnect()

        mock_subscription.unsubscribe.assert_called_once()
        mock_client.stop_auto_message_fetching.assert_awaited_once()

    def test_disconnect_stops_dispatch_thread(self):
        """Issue 52: disconnect() must join the dispatch thread promptly
        (not hang) and leave the transport ready for a clean reconnect."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda msg, sender: None)
        self.assertIsNotNone(transport._dispatch_thread)

        transport.disconnect()

        self.assertIsNone(transport._dispatch_thread)
        self.assertIsNone(transport._dispatch_queue)

    def test_reconnect_after_disconnect_starts_a_fresh_loop(self):
        """Regression guard: disconnect() tears down the background loop
        thread entirely, so a subsequent connect() must be able to spin up
        a new one rather than reusing a stopped loop."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.disconnect()

        transport.connect("/dev/ttyUSB0")
        self.assertTrue(transport.is_connected)
        transport.disconnect()

    def test_disconnect_does_not_hang_or_raise_when_mc_disconnect_blocks(self):
        """Issue 53: mirrors the Meshtastic fix for the same class of bug -
        mc.disconnect() blocking indefinitely must not hang disconnect()
        forever, and - since every real caller treats disconnect() as
        safe-to-call - must not raise either."""
        async def blocking_disconnect():
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.disconnect = AsyncMock(side_effect=blocking_disconnect)
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport._SEND_TIMEOUT_SECONDS = 0.05  # keep the test fast

        transport.disconnect()  # must return, not hang or raise

        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport._mc)

    def test_disconnect_skips_loop_close_when_loop_thread_still_alive(self):
        """Issue 53: loop.close() raises RuntimeError if the loop thread
        is still actually running - disconnect() must never raise, so it
        must skip close() rather than call it unguarded in that case.
        Simulates the loop thread outliving its join() timeout directly
        (real repro is a low-probability race - see the plan's write-up).

        Only join()/is_alive() are patched on the real thread instance,
        and close() is patched (via patch.object, auto-restored) on the
        real loop instance - self._mc.disconnect()'s own _run_coro() call
        still needs a genuine event loop to run against, so self._loop
        itself is never replaced."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        transport._loop_thread.join = MagicMock()  # no-op: simulates a timed-out join
        transport._loop_thread.is_alive = MagicMock(return_value=True)

        with patch.object(transport._loop, 'close') as mock_close:
            transport.disconnect()  # must return, not raise
            mock_close.assert_not_called()

        self.assertIsNone(transport._loop)
        self.assertIsNone(transport._loop_thread)
        self.assertIsNone(transport._mc)


# ---------------------------------------------------------------------------
# Send tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportSend(unittest.TestCase):
    """Tests for send method."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_send_calls_send_msg_with_correct_args(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.send("hello world", "aabbccddeeff")

        mock_client.commands.send_msg.assert_awaited_once_with(
            "aabbccddeeff", "hello world"
        )
        transport.disconnect()

    def test_send_raises_when_not_connected(self):
        transport = MeshCoreSerialTransport()

        with self.assertRaises(TransportConnectionError) as ctx:
            transport.send("hello", "aabbccddeeff")
        self.assertIn("Not connected", str(ctx.exception))

    def test_send_raises_on_send_msg_failure(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_msg = AsyncMock(
            side_effect=RuntimeError("device error")
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        with self.assertRaises(TransportSendError) as ctx:
            transport.send("hello", "aabbccddeeff")
        self.assertIn("Failed to send message", str(ctx.exception))
        transport.disconnect()

    def test_send_raises_on_error_event(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_msg = AsyncMock(
            return_value=FakeEvent(FakeEventType.ERROR, payload="bad destination")
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        with self.assertRaises(TransportSendError) as ctx:
            transport.send("hello", "aabbccddeeff")
        self.assertIn("bad destination", str(ctx.exception))
        transport.disconnect()

    def test_send_raises_timeout_error_when_send_msg_blocks(self):
        """Same guarantee as Issue 21's Meshtastic fix: send() must give up
        after _SEND_MSG_TIMEOUT_SECONDS rather than hanging forever."""
        async def blocking_send_msg(*args, **kwargs):
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.commands.send_msg = AsyncMock(side_effect=blocking_send_msg)
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport._SEND_MSG_TIMEOUT_SECONDS = 0.05  # keep the test fast

        with self.assertRaises(TransportSendError) as ctx:
            transport.send("hello", "aabbccddeeff")
        self.assertIn("timed out", str(ctx.exception))
        transport.disconnect()


# ---------------------------------------------------------------------------
# Message handler tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportMessageHandler(unittest.TestCase):
    """Tests for set_message_handler and remove_message_handler."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_set_handler_before_connect(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        handler = MagicMock()
        transport.set_message_handler(handler)

        # Should not subscribe yet (not connected)
        mock_client.subscribe.assert_not_called()

        # Subscribe should happen on connect
        transport.connect("/dev/ttyUSB0")
        mock_client.subscribe.assert_called_once()
        transport.disconnect()

    def test_set_handler_after_connect(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        handler = MagicMock()
        transport.set_message_handler(handler)

        mock_client.subscribe.assert_called_once()
        transport.disconnect()

    def test_set_handler_replaces_previous(self):
        mock_client = MockMeshCoreClient()
        mock_subscription = MagicMock()
        mock_client.subscribe.return_value = mock_subscription
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        transport.set_message_handler(MagicMock())
        mock_client.subscribe.reset_mock()

        transport.set_message_handler(MagicMock())

        mock_subscription.unsubscribe.assert_called_once()
        mock_client.subscribe.assert_called_once()
        transport.disconnect()

    def test_remove_handler(self):
        mock_client = MockMeshCoreClient()
        mock_subscription = MagicMock()
        mock_client.subscribe.return_value = mock_subscription
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda m, s: None)

        transport.remove_message_handler()

        mock_subscription.unsubscribe.assert_called_once()
        self.assertIsNone(transport._handler)
        transport.disconnect()

    def test_remove_handler_stops_dispatch_thread(self):
        """Issue 52: remove_message_handler() must join the dispatch
        thread too, not just unsubscribe CONTACT_MSG_RECV."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda m, s: None)
        self.assertIsNotNone(transport._dispatch_thread)

        transport.remove_message_handler()

        self.assertIsNone(transport._dispatch_thread)
        transport.disconnect()

    def test_remove_handler_stops_auto_message_fetching(self):
        """Issue 50: the active-pull mechanism started by _subscribe()
        must be torn down symmetrically, not just the CONTACT_MSG_RECV
        subscription."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda m, s: None)

        transport.remove_message_handler()

        mock_client.stop_auto_message_fetching.assert_awaited_once()
        transport.disconnect()

    def test_subscribe_starts_auto_message_fetching(self):
        """Issue 50: MeshCore's companion protocol only fires
        CONTACT_MSG_RECV as the reply to an explicit pull - subscribing
        must also start that pull (meshcore_py's
        start_auto_message_fetching()), or a real incoming message never
        reaches the registered handler even though it reaches the radio
        (confirmed via real hardware)."""
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(lambda m, s: None)

        mock_client.start_auto_message_fetching.assert_awaited_once()
        transport.disconnect()

    def test_set_handler_raises_clear_error_when_subscribe_blocks(self):
        """Issue 63: a bare FutureTimeoutError has an empty str(), which
        surfaced as a blank, useless "Initialization error:" to the
        operator - set_message_handler() must give up with a real
        message after _SUBSCRIBE_TIMEOUT_SECONDS, same guarantee as
        send()'s Issue 21-style timeout."""
        async def blocking_start_auto_message_fetching(*args, **kwargs):
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.start_auto_message_fetching = AsyncMock(
            side_effect=blocking_start_auto_message_fetching
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport._SUBSCRIBE_TIMEOUT_SECONDS = 0.05  # keep the test fast

        with self.assertRaises(TransportConnectionError) as ctx:
            transport.set_message_handler(lambda m, s: None)
        self.assertIn("Timed out", str(ctx.exception))
        transport.disconnect()


# ---------------------------------------------------------------------------
# Message receiving tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportReceive(unittest.TestCase):
    """Tests for the internal event-subscription callback."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def _connect_and_capture_callback(self, mock_client, handler):
        _install_mock_meshcore(mock_client)
        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.set_message_handler(handler)
        _, callback = mock_client.subscribe.call_args[0]
        return transport, callback

    def test_receive_text_message_calls_handler(self):
        mock_client = MockMeshCoreClient()
        received = []
        done = threading.Event()

        def handler(text, sender):
            received.append((text, sender))
            done.set()

        transport, callback = self._connect_and_capture_callback(mock_client, handler)

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello World", "pubkey_prefix": "112233445566"},
        )
        asyncio.run(callback(event))

        self.assertTrue(done.wait(timeout=2), "handler was not called")
        self.assertEqual(received, [("Hello World", "112233445566")])
        transport.disconnect()

    def test_receive_with_no_handler(self):
        mock_client = MockMeshCoreClient()
        transport, callback = self._connect_and_capture_callback(
            mock_client, MagicMock()
        )
        transport.remove_message_handler()

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello", "pubkey_prefix": "112233445566"},
        )
        asyncio.run(callback(event))  # Should not raise
        transport.disconnect()

    def test_receive_ignores_event_without_text(self):
        mock_client = MockMeshCoreClient()
        handler = MagicMock()
        transport, callback = self._connect_and_capture_callback(mock_client, handler)

        event = FakeEvent(FakeEventType.CONTACT_MSG_RECV, payload={})
        asyncio.run(callback(event))

        handler.assert_not_called()
        transport.disconnect()

    def test_receive_ignores_event_without_sender(self):
        """The handler is useless without knowing who to reply to - a
        text payload with no pubkey_prefix must be dropped too, not just
        one with no text."""
        mock_client = MockMeshCoreClient()
        handler = MagicMock()
        transport, callback = self._connect_and_capture_callback(mock_client, handler)

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV, payload={"text": "Hello World"}
        )
        asyncio.run(callback(event))

        handler.assert_not_called()
        transport.disconnect()

    def test_receive_handles_handler_exception(self):
        mock_client = MockMeshCoreClient()
        done = threading.Event()

        def bad_handler(msg, sender):
            try:
                raise ValueError("Handler error")
            finally:
                done.set()

        transport, callback = self._connect_and_capture_callback(
            mock_client, bad_handler
        )

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello", "pubkey_prefix": "112233445566"},
        )
        asyncio.run(callback(event))  # Should not raise

        self.assertTrue(done.wait(timeout=2), "handler never ran")
        transport.disconnect()

    def test_multiple_messages_dispatched_in_order(self):
        """Issue 52: the dispatch queue must preserve message order, the
        property a naive thread-per-message approach would risk losing."""
        mock_client = MockMeshCoreClient()
        received = []
        all_done = threading.Event()

        def handler(text, sender):
            received.append(text)
            if len(received) == 3:
                all_done.set()

        transport, callback = self._connect_and_capture_callback(mock_client, handler)
        for i in range(3):
            event = FakeEvent(
                FakeEventType.CONTACT_MSG_RECV,
                payload={"text": f"msg-{i}", "pubkey_prefix": "112233445566"},
            )
            asyncio.run(callback(event))

        self.assertTrue(all_done.wait(timeout=2), "not all messages were dispatched")
        self.assertEqual(received, ["msg-0", "msg-1", "msg-2"])
        transport.disconnect()

    def test_handler_calling_send_does_not_deadlock(self):
        """Issue 52: a handler that calls transport.send() (e.g. a server
        ACKing a received chunk) must not deadlock against _on_event's own
        background loop thread. Reproduced against real hardware as an
        exact, repeatable 10s hang before this fix; runs the callback ON
        the transport's own loop (transport._loop), not an ad-hoc one, to
        faithfully reproduce the thread the real library actually invokes
        subscribers on - a plain asyncio.run() in the test's own thread
        would not exercise the reentrancy this guards against."""
        mock_client = MockMeshCoreClient()
        done = threading.Event()
        outcome = {}

        def handler(text, sender):
            try:
                transport.send("ACK", sender)
            except Exception as e:
                outcome["error"] = e
            finally:
                done.set()

        transport, callback = self._connect_and_capture_callback(mock_client, handler)
        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello", "pubkey_prefix": "112233445566"},
        )
        future = asyncio.run_coroutine_threadsafe(callback(event), transport._loop)
        future.result(timeout=5)

        self.assertTrue(done.wait(timeout=2), "handler never completed")
        self.assertNotIn(
            "error", outcome, f"send() from handler raised: {outcome.get('error')}"
        )
        transport.disconnect()


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportProperties(unittest.TestCase):
    """Tests for is_connected and local_node_id properties."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_is_connected_before_connect(self):
        transport = MeshCoreSerialTransport()
        self.assertFalse(transport.is_connected)

    def test_is_connected_after_connect(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        self.assertTrue(transport.is_connected)
        transport.disconnect()

    def test_local_node_id_before_connect(self):
        transport = MeshCoreSerialTransport()
        self.assertIsNone(transport.local_node_id)

    def test_local_node_id_truncates_to_6_byte_prefix(self):
        mock_client = MockMeshCoreClient(public_key="aa11bb22cc33" + "00" * 26)
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        self.assertEqual(transport.local_node_id, "aa11bb22cc33")
        self.assertEqual(len(transport.local_node_id), 12)
        transport.disconnect()

    def test_local_node_id_after_disconnect(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport.disconnect()
        self.assertIsNone(transport.local_node_id)


# ---------------------------------------------------------------------------
# check_alive tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportCheckAlive(unittest.TestCase):
    """Tests for check_alive()."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_returns_false_when_not_connected(self):
        transport = MeshCoreSerialTransport()
        self.assertFalse(transport.check_alive())

    def test_returns_true_on_device_info_response(self):
        mock_client = MockMeshCoreClient()
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertTrue(transport.check_alive())
        mock_client.commands.send_device_query.assert_awaited_once()
        transport.disconnect()

    def test_returns_false_on_error_response(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.ERROR)
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertFalse(transport.check_alive())
        transport.disconnect()

    def test_returns_false_on_exception(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            side_effect=RuntimeError("write failed")
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertFalse(transport.check_alive())
        transport.disconnect()

    def test_returns_false_on_timeout(self):
        async def blocking_query():
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            side_effect=blocking_query
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertFalse(transport.check_alive(timeout_seconds=0.05))
        transport.disconnect()


class TestMeshCoreSerialTransportGetDeviceModel(unittest.TestCase):
    """Tests for get_device_model() (Issue 54)."""

    def tearDown(self):
        _uninstall_mock_meshcore()

    def test_returns_none_when_not_connected(self):
        transport = MeshCoreSerialTransport()
        self.assertIsNone(transport.get_device_model())

    def test_returns_model_on_device_info_response(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.DEVICE_INFO, payload={"model": "Heltec V3"})
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertEqual(transport.get_device_model(), "Heltec V3")
        mock_client.commands.send_device_query.assert_awaited_once()
        transport.disconnect()

    def test_returns_none_on_error_response(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.ERROR)
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertIsNone(transport.get_device_model())
        transport.disconnect()

    def test_returns_none_when_payload_has_no_model_key(self):
        """Old firmware (fw_ver < 3) - the DEVICE_INFO payload simply
        omits "model" entirely rather than sending an empty value."""
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.DEVICE_INFO, payload={"fw ver": 2})
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertIsNone(transport.get_device_model())
        transport.disconnect()

    def test_returns_none_when_model_is_empty_or_whitespace(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            return_value=FakeEvent(FakeEventType.DEVICE_INFO, payload={"model": "   "})
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertIsNone(transport.get_device_model())
        transport.disconnect()

    def test_returns_none_on_exception(self):
        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            side_effect=RuntimeError("write failed")
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertIsNone(transport.get_device_model())
        transport.disconnect()

    def test_returns_none_on_timeout(self):
        async def blocking_query():
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.commands.send_device_query = AsyncMock(
            side_effect=blocking_query
        )
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertIsNone(transport.get_device_model(timeout_seconds=0.05))
        transport.disconnect()


# ---------------------------------------------------------------------------
# scan_for_reconnect_candidates tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportScanForReconnectCandidates(unittest.TestCase):
    """Tests for scan_for_reconnect_candidates() (Story 30.4) - mirrors
    tests/test_meshtastic_serial_transport.py's equivalent class. Every
    test here mocks both the scan and the relay-board probe: the real
    implementation calls core.device_scan.scan_serial_devices_detailed()
    (a genuine serial.tools.list_ports.comports() scan) and
    transport.power_control.probe_relay_board_id() (a genuine serial
    connect attempt) - leaving either unmocked would exercise real
    hardware I/O against whatever's actually plugged into the machine
    running the tests, which can hang indefinitely instead of failing
    fast."""

    def test_returns_paths_from_detailed_scan(self):
        from core.device_scan import DeviceInfo

        transport = MeshCoreSerialTransport()
        devices = [
            DeviceInfo(path="/dev/ttyUSB0", serial_number="A1", description="x"),
            DeviceInfo(path="/dev/ttyUSB1", serial_number=None, description="y"),
        ]
        with patch(
            "core.device_scan.scan_serial_devices_detailed",
            return_value=devices,
        ), patch(
            "transport.power_control.probe_relay_board_id", return_value=None
        ):
            result = transport.scan_for_reconnect_candidates()

        self.assertEqual(result, ["/dev/ttyUSB0", "/dev/ttyUSB1"])

    def test_returns_empty_list_when_no_devices(self):
        transport = MeshCoreSerialTransport()
        with patch(
            "core.device_scan.scan_serial_devices_detailed", return_value=[]
        ), patch(
            "transport.power_control.probe_relay_board_id", return_value=None
        ):
            result = transport.scan_for_reconnect_candidates()

        self.assertEqual(result, [])

    def test_excludes_relay_board_port(self):
        """Issue 48's fix, mirrored for MeshCore: DeviceWatchdog._try_candidate()
        has no relay-board awareness of its own (transport-agnostic by
        design), so the filtering has to happen here - otherwise recovery
        sends the relay board a MeshCore connect attempt it can never
        answer correctly."""
        from core.device_scan import DeviceInfo

        transport = MeshCoreSerialTransport()
        devices = [
            DeviceInfo(path="/dev/ttyUSB0", serial_number="A1", description="x"),
            DeviceInfo(path="/dev/ttyRELAY", serial_number="B2", description="y"),
        ]

        def fake_probe(path, *args, **kwargs):
            return "000E55D8" if path == "/dev/ttyRELAY" else None

        with patch(
            "core.device_scan.scan_serial_devices_detailed",
            return_value=devices,
        ), patch(
            "transport.power_control.probe_relay_board_id", side_effect=fake_probe
        ):
            result = transport.scan_for_reconnect_candidates()

        self.assertEqual(result, ["/dev/ttyUSB0"])


class TestMeshCoreSerialTransportValidateDestination(unittest.TestCase):
    """Story 30.2: MeshCore validates its own addressing format - a
    hex-encoded public key or public-key prefix - distinct from
    Meshtastic's '!hex8' rule."""

    def test_valid_full_public_key(self):
        MeshCoreSerialTransport().validate_destination("ab" * 32)  # no raise

    def test_valid_prefix(self):
        MeshCoreSerialTransport().validate_destination("a1b2c3d4e5f6")  # no raise

    def test_empty_destination_raises(self):
        with self.assertRaises(ValueError):
            MeshCoreSerialTransport().validate_destination("")

    def test_none_destination_raises(self):
        with self.assertRaises(ValueError):
            MeshCoreSerialTransport().validate_destination(None)

    def test_non_hex_characters_raise(self):
        with self.assertRaises(ValueError):
            MeshCoreSerialTransport().validate_destination("zzzznotahexstring")

    def test_odd_length_raises(self):
        with self.assertRaises(ValueError):
            MeshCoreSerialTransport().validate_destination("abc")


class TestMeshCoreSerialTransportMaxChunkSize(unittest.TestCase):
    """Issue 51: MeshCore needs its own, smaller chunk size - the default
    170 (Meshtastic-tuned) exceeds MeshCore's MAX_TEXT_LEN and is rejected
    outright by the firmware (confirmed via real hardware)."""

    def test_max_chunk_size_matches_meshcore_constant(self):
        from core.constants import MESHCORE_MAX_CHUNK_SIZE

        self.assertEqual(
            MeshCoreSerialTransport().max_chunk_size, MESHCORE_MAX_CHUNK_SIZE
        )

    def test_max_chunk_size_stays_under_meshcore_text_limit(self):
        """Documents (and guards) the invariant the constant depends on -
        if MAX_TOTAL_CHUNKS or the wire format ever changes such that this
        no longer holds, this test fails loudly instead of silently
        repeating Issue 51."""
        from core.constants import (
            CHUNK_DELIMITER,
            CHUNK_INDEX_DELIMITER,
            MAX_TOTAL_CHUNKS,
            MESHCORE_MAX_CHUNK_SIZE,
            MESHCORE_MAX_TEXT_LEN,
            MSG_BTC_TX,
            SESSION_ID_LENGTH,
        )

        worst_case_digits = len(str(MAX_TOTAL_CHUNKS))
        worst_case_overhead = (
            len(MSG_BTC_TX)
            + 3 * len(CHUNK_DELIMITER)
            + SESSION_ID_LENGTH
            + len(CHUNK_INDEX_DELIMITER)
            + 2 * worst_case_digits
        )
        self.assertLessEqual(
            MESHCORE_MAX_CHUNK_SIZE + worst_case_overhead, MESHCORE_MAX_TEXT_LEN
        )


if __name__ == "__main__":
    unittest.main()
