"""Tests for transport/meshcore_serial.py — MeshCoreSerialTransport implementation.

Tests verify:
- Connection lifecycle (connect, disconnect, reconnect)
- Message sending with proper arguments
- Message receiving via the event-subscription callback
- Error handling for various failure modes
- Handler management and subscription lifecycle
- Liveness checking (check_alive)
"""
import sys
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
        after _SEND_TIMEOUT_SECONDS rather than hanging forever."""
        import asyncio

        async def blocking_send_msg(*args, **kwargs):
            await asyncio.sleep(3600)

        mock_client = MockMeshCoreClient()
        mock_client.commands.send_msg = AsyncMock(side_effect=blocking_send_msg)
        _install_mock_meshcore(mock_client)

        transport = MeshCoreSerialTransport()
        transport.connect("/dev/ttyUSB0")
        transport._SEND_TIMEOUT_SECONDS = 0.05  # keep the test fast

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
        handler = MagicMock()
        transport, callback = self._connect_and_capture_callback(mock_client, handler)

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello World", "pubkey_prefix": "112233445566"},
        )
        import asyncio
        asyncio.run(callback(event))

        handler.assert_called_once_with("Hello World", "112233445566")
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
        import asyncio
        asyncio.run(callback(event))  # Should not raise
        transport.disconnect()

    def test_receive_ignores_event_without_text(self):
        mock_client = MockMeshCoreClient()
        handler = MagicMock()
        transport, callback = self._connect_and_capture_callback(mock_client, handler)

        event = FakeEvent(FakeEventType.CONTACT_MSG_RECV, payload={})
        import asyncio
        asyncio.run(callback(event))

        handler.assert_not_called()
        transport.disconnect()

    def test_receive_handles_handler_exception(self):
        mock_client = MockMeshCoreClient()

        def bad_handler(msg, sender):
            raise ValueError("Handler error")

        transport, callback = self._connect_and_capture_callback(
            mock_client, bad_handler
        )

        event = FakeEvent(
            FakeEventType.CONTACT_MSG_RECV,
            payload={"text": "Hello", "pubkey_prefix": "112233445566"},
        )
        import asyncio
        asyncio.run(callback(event))  # Should not raise
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
        import asyncio

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


# ---------------------------------------------------------------------------
# scan_for_reconnect_candidates tests
# ---------------------------------------------------------------------------


class TestMeshCoreSerialTransportScanForReconnectCandidates(unittest.TestCase):
    """MeshCore device discovery is deferred (Story 30.4) - this must
    return an empty list rather than raising, per BaseTransport's
    contract."""

    def test_returns_empty_list(self):
        transport = MeshCoreSerialTransport()
        self.assertEqual(transport.scan_for_reconnect_candidates(), [])


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


if __name__ == "__main__":
    unittest.main()
