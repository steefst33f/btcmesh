"""Tests for transport/meshtastic_serial.py — MeshtasticSerialTransport implementation.

Tests verify:
- Connection lifecycle (connect, disconnect, reconnect)
- Message sending with proper arguments
- Message receiving with pubsub filtering
- Self-message filtering
- Error handling for various failure modes
- Handler management and subscription lifecycle
- Node ID formatting
- Text extraction from packets
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

from transport.base import (
    TransportConnectionError,
    TransportSendError,
)
from transport.meshtastic_serial import MeshtasticSerialTransport


# ---------------------------------------------------------------------------
# Helpers: Mock Meshtastic objects
# ---------------------------------------------------------------------------


class MockMyInfo:
    """Mock for iface.myInfo."""
    def __init__(self, my_node_num):
        self.my_node_num = my_node_num


class MockSerialInterface:
    """Mock Meshtastic SerialInterface."""
    def __init__(self, my_node_num=0xDEADBEEF):
        self.myInfo = MockMyInfo(my_node_num)
        self.noProto = False
        self.close_called = False

    def connect(self):
        pass

    def waitForConfig(self):
        pass

    def close(self):
        self.close_called = True

    def sendText(self, text, destinationId, wantAck):
        pass


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportConnect(unittest.TestCase):
    """Tests for connect method."""

    def setUp(self):
        """Set up mocks for meshtastic module."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

    def tearDown(self):
        """Clean up mocks."""
        if 'meshtastic' in sys.modules:
            del sys.modules['meshtastic']
        if 'meshtastic.serial_interface' in sys.modules:
            del sys.modules['meshtastic.serial_interface']

    def test_connect_with_explicit_device_path(self):
        """Test connecting with explicit device path."""
        mock_iface = MockSerialInterface(0xAABBCCDD)
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect("/dev/ttyUSB0")

        self.assertTrue(transport.is_connected)
        self.assertEqual(transport.local_node_id, "!aabbccdd")
        self.mock_meshtastic.serial_interface.SerialInterface.assert_called_once_with(
            devPath="/dev/ttyUSB0", connectNow=False
        )

    def test_connect_with_auto_detect(self):
        """Test connecting with auto-detect (device_path=None)."""
        mock_iface = MockSerialInterface(0x12345678)
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect(None)

        self.assertTrue(transport.is_connected)
        self.assertEqual(transport.local_node_id, "!12345678")
        self.mock_meshtastic.serial_interface.SerialInterface.assert_called_once_with(
            connectNow=False
        )

    def test_connect_raises_when_already_connected(self):
        """Test that connecting when already connected raises error."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("Already connected", str(ctx.exception))

    def test_connect_raises_when_meshtastic_not_installed(self):
        """Test that ImportError is handled correctly."""
        self.mock_meshtastic.serial_interface.SerialInterface.side_effect = ImportError(
            "No module named 'meshtastic'"
        )

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_connect_raises_on_no_device_error(self):
        """Test that NoDeviceError is caught and re-raised."""
        NoDeviceError = type('NoDeviceError', (Exception,), {})
        self.mock_meshtastic.serial_interface.SerialInterface.side_effect = NoDeviceError(
            "No Meshtastic device found"
        )

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("No Meshtastic device found", str(ctx.exception))

    def test_connect_raises_on_generic_exception(self):
        """Test that generic exceptions are caught and re-raised."""
        self.mock_meshtastic.serial_interface.SerialInterface.side_effect = RuntimeError(
            "Connection timeout"
        )

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("Failed to connect", str(ctx.exception))

    def test_connect_closes_iface_when_handshake_times_out(self):
        """Test that a failure during the handshake (connect()/waitForConfig(),
        which runs after the serial port is already open) still closes the
        iface instead of leaking the open port/reader thread.

        Regression test: meshtastic.serial_interface.SerialInterface() used
        to perform the handshake inside its own constructor, so if it failed
        partway through (e.g. "Timed out waiting for connection completion"),
        the assignment to `iface` never completed and there was no reference
        left to close - leaking an exclusive OS-level lock on the serial port
        for the rest of the process's lifetime, requiring an app restart.
        """
        mock_iface = MockSerialInterface()
        mock_iface.connect = MagicMock(
            side_effect=Exception("Timed out waiting for connection completion")
        )
        mock_iface.close = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect("/dev/ttyUSB0")

        self.assertIn("Failed to connect", str(ctx.exception))
        self.assertIn("Timed out waiting for connection completion", str(ctx.exception))
        mock_iface.close.assert_called_once()
        self.mock_meshtastic.serial_interface.SerialInterface.assert_called_once_with(
            devPath="/dev/ttyUSB0", connectNow=False
        )

    def test_connect_raises_when_myinfo_missing(self):
        """Test that missing myInfo raises error and closes interface."""
        mock_iface = MagicMock()
        mock_iface.myInfo = None
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("could not retrieve device info", str(ctx.exception))
        mock_iface.close.assert_called_once()

    def test_connect_raises_when_node_num_missing(self):
        """Test that missing my_node_num raises error and closes interface."""
        mock_iface = MagicMock()
        mock_iface.myInfo = MagicMock()
        mock_iface.myInfo.my_node_num = None
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        with self.assertRaises(TransportConnectionError) as ctx:
            transport.connect()
        self.assertIn("could not retrieve device info", str(ctx.exception))
        mock_iface.close.assert_called_once()


# ---------------------------------------------------------------------------
# Disconnect tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportDisconnect(unittest.TestCase):
    """Tests for disconnect method."""

    def setUp(self):
        """Set up mocks for meshtastic and pubsub."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

        self.mock_pubsub = MagicMock()
        sys.modules['pubsub'] = self.mock_pubsub
        sys.modules['pubsub.pub'] = self.mock_pubsub.pub

    def tearDown(self):
        """Clean up mocks."""
        for mod in ['meshtastic', 'meshtastic.serial_interface', 'pubsub', 'pubsub.pub']:
            if mod in sys.modules:
                del sys.modules[mod]

    def test_disconnect_closes_interface(self):
        """Test that disconnect closes the interface."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        self.assertTrue(transport.is_connected)

        transport.disconnect()

        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport.local_node_id)
        self.assertTrue(mock_iface.close_called)

    def test_disconnect_idempotent(self):
        """Test that disconnect can be called multiple times safely."""
        transport = MeshtasticSerialTransport()
        transport.disconnect()  # Should not raise
        transport.disconnect()  # Should not raise

    def test_disconnect_handles_close_exception(self):
        """Test that exceptions during close are silently caught."""
        mock_iface = MagicMock()
        mock_iface.myInfo = MockMyInfo(0x12345678)
        mock_iface.close.side_effect = RuntimeError("Close failed")
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.disconnect()  # Should not raise
        self.assertFalse(transport.is_connected)

    def test_disconnect_unsubscribes_handler(self):
        """Test that disconnect unsubscribes from pubsub."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.set_message_handler(lambda msg, sender: None)

        transport.disconnect()

        # Verify unsubscribe was called
        self.mock_pubsub.pub.unsubscribe.assert_called()


# ---------------------------------------------------------------------------
# Send tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportSend(unittest.TestCase):
    """Tests for send method."""

    def setUp(self):
        """Set up mocks for meshtastic."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

    def tearDown(self):
        """Clean up mocks."""
        for mod in ['meshtastic', 'meshtastic.serial_interface']:
            if mod in sys.modules:
                del sys.modules[mod]

    def test_send_calls_sendtext_with_correct_args(self):
        """Test that send calls sendText with correct parameters."""
        mock_iface = MockSerialInterface()
        mock_iface.sendText = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.send("hello world", "!deadbeef")

        mock_iface.sendText.assert_called_once_with(
            text="hello world",
            destinationId="!deadbeef",
            wantAck=False,
        )

    def test_send_raises_when_not_connected(self):
        """Test that send raises when not connected."""
        transport = MeshtasticSerialTransport()

        with self.assertRaises(TransportConnectionError) as ctx:
            transport.send("hello", "!deadbeef")
        self.assertIn("Not connected", str(ctx.exception))

    def test_send_raises_on_sendtext_failure(self):
        """Test that send exceptions are wrapped in TransportSendError."""
        mock_iface = MockSerialInterface()
        mock_iface.sendText = MagicMock(side_effect=RuntimeError("Device error"))
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        with self.assertRaises(TransportSendError) as ctx:
            transport.send("hello", "!deadbeef")
        self.assertIn("Failed to send message", str(ctx.exception))


# ---------------------------------------------------------------------------
# Message handler tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportMessageHandler(unittest.TestCase):
    """Tests for set_message_handler and remove_message_handler."""

    def setUp(self):
        """Set up mocks for meshtastic and pubsub."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

        self.mock_pubsub = MagicMock()
        sys.modules['pubsub'] = self.mock_pubsub
        sys.modules['pubsub.pub'] = self.mock_pubsub.pub

    def tearDown(self):
        """Clean up mocks."""
        for mod in ['meshtastic', 'meshtastic.serial_interface', 'pubsub', 'pubsub.pub']:
            if mod in sys.modules:
                del sys.modules[mod]

    def test_set_handler_before_connect(self):
        """Test that setting handler before connect defers subscription."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        handler = MagicMock()
        transport.set_message_handler(handler)

        # Should not subscribe yet (not connected)
        self.mock_pubsub.pub.subscribe.assert_not_called()

        # Subscribe should happen on connect
        transport.connect()
        self.mock_pubsub.pub.subscribe.assert_called_once()

    def test_set_handler_after_connect(self):
        """Test that setting handler after connect subscribes immediately."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        # Should subscribe immediately
        self.mock_pubsub.pub.subscribe.assert_called_once()

    def test_set_handler_replaces_previous(self):
        """Test that setting a new handler replaces the old one."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler1 = MagicMock()
        handler2 = MagicMock()

        transport.set_message_handler(handler1)
        self.mock_pubsub.pub.subscribe.reset_mock()

        transport.set_message_handler(handler2)

        # Should unsubscribe old and subscribe new
        self.mock_pubsub.pub.unsubscribe.assert_called_once()
        self.mock_pubsub.pub.subscribe.assert_called_once()

    def test_remove_handler(self):
        """Test removing the message handler."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.set_message_handler(lambda m, s: None)

        self.mock_pubsub.pub.unsubscribe.reset_mock()

        transport.remove_message_handler()

        self.mock_pubsub.pub.unsubscribe.assert_called_once()
        self.assertIsNone(transport._handler)


# ---------------------------------------------------------------------------
# Message receiving tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportReceive(unittest.TestCase):
    """Tests for _on_meshtastic_receive callback."""

    def setUp(self):
        """Set up mocks for meshtastic."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

    def tearDown(self):
        """Clean up mocks."""
        for mod in ['meshtastic', 'meshtastic.serial_interface']:
            if mod in sys.modules:
                del sys.modules[mod]

    def test_receive_text_message_calls_handler(self):
        """Test that text messages trigger the handler."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        # Simulate receiving a text message
        packet = {
            'from': 0x11223344,
            'fromId': '!11223344',
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': 'Hello World',
            }
        }
        transport._on_meshtastic_receive(packet)

        handler.assert_called_once_with('Hello World', '!11223344')

    def test_receive_filters_self_messages(self):
        """Test that self-messages are filtered out."""
        mock_iface = MockSerialInterface(0xDEADBEEF)
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        # Simulate receiving own message (self-message)
        packet = {
            'from': 0xDEADBEEF,
            'fromId': '!deadbeef',
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': 'Echo',
            }
        }
        transport._on_meshtastic_receive(packet)

        # Handler should NOT be called for self-messages
        handler.assert_not_called()

    def test_receive_filters_non_text_messages(self):
        """Test that non-text messages are filtered."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        # Simulate receiving position message
        packet = {
            'from': 0x11223344,
            'fromId': '!11223344',
            'decoded': {
                'portnum': 'POSITION_APP',
                'latitude': 12.34,
            }
        }
        transport._on_meshtastic_receive(packet)

        handler.assert_not_called()

    def test_receive_ignores_packet_without_decoded(self):
        """Test that packets without decoded section are ignored."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        packet = {'from': 0x11223344}
        transport._on_meshtastic_receive(packet)

        handler.assert_not_called()

    def test_receive_with_no_handler(self):
        """Test that receiving without handler doesn't raise."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        packet = {
            'from': 0x11223344,
            'fromId': '!11223344',
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': 'Hello',
            }
        }
        transport._on_meshtastic_receive(packet)  # Should not raise

    def test_receive_payload_fallback_to_bytes(self):
        """Test extracting text from payload bytes when text field missing."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        handler = MagicMock()
        transport.set_message_handler(handler)

        packet = {
            'from': 0x11223344,
            'fromId': '!11223344',
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'payload': b'Hello from bytes',
            }
        }
        transport._on_meshtastic_receive(packet)

        handler.assert_called_once_with('Hello from bytes', '!11223344')

    def test_receive_handles_handler_exception(self):
        """Test that exceptions in handler don't break receive."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()

        def bad_handler(msg, sender):
            raise ValueError("Handler error")

        transport.set_message_handler(bad_handler)

        packet = {
            'from': 0x11223344,
            'fromId': '!11223344',
            'decoded': {
                'portnum': 'TEXT_MESSAGE_APP',
                'text': 'Hello',
            }
        }
        transport._on_meshtastic_receive(packet)  # Should not raise


# ---------------------------------------------------------------------------
# Utility method tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportUtilities(unittest.TestCase):
    """Tests for utility helper methods."""

    def test_format_node_id(self):
        """Test node ID formatting."""
        self.assertEqual(
            MeshtasticSerialTransport._format_node_id(0xDEADBEEF),
            "!deadbeef"
        )
        self.assertEqual(
            MeshtasticSerialTransport._format_node_id(0x12345678),
            "!12345678"
        )
        self.assertEqual(
            MeshtasticSerialTransport._format_node_id(0x00000001),
            "!00000001"
        )

    def test_extract_text_from_packet_text_field(self):
        """Test extracting text from decoded.text."""
        decoded = {'text': 'Hello World'}
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertEqual(result, 'Hello World')

    def test_extract_text_from_packet_payload_field(self):
        """Test extracting text from decoded.payload bytes."""
        decoded = {'payload': b'Hello from bytes'}
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertEqual(result, 'Hello from bytes')

    def test_extract_text_prefers_text_over_payload(self):
        """Test that text field is preferred over payload."""
        decoded = {
            'text': 'Text field',
            'payload': b'Payload field',
        }
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertEqual(result, 'Text field')

    def test_extract_text_returns_none_for_empty(self):
        """Test that empty text is treated as None."""
        decoded = {'text': ''}
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertIsNone(result)

    def test_extract_text_handles_invalid_utf8(self):
        """Test that invalid UTF-8 in payload is handled gracefully."""
        decoded = {'payload': b'\xff\xfe\xfd'}
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertIsNone(result)

    def test_extract_text_returns_none_for_no_text(self):
        """Test that missing text and payload returns None."""
        decoded = {}
        result = MeshtasticSerialTransport._extract_text_from_packet(decoded)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Properties tests
# ---------------------------------------------------------------------------


class TestMeshtasticSerialTransportProperties(unittest.TestCase):
    """Tests for is_connected and local_node_id properties."""

    def setUp(self):
        """Set up mocks for meshtastic."""
        self.mock_meshtastic = MagicMock()
        self.mock_serial_iface = MagicMock()
        self.mock_meshtastic.serial_interface.SerialInterface = MagicMock()
        sys.modules['meshtastic'] = self.mock_meshtastic
        sys.modules['meshtastic.serial_interface'] = self.mock_serial_iface

    def tearDown(self):
        """Clean up mocks."""
        for mod in ['meshtastic', 'meshtastic.serial_interface']:
            if mod in sys.modules:
                del sys.modules[mod]

    def test_is_connected_before_connect(self):
        """Test is_connected before connecting."""
        transport = MeshtasticSerialTransport()
        self.assertFalse(transport.is_connected)

    def test_is_connected_after_connect(self):
        """Test is_connected after connecting."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        self.assertTrue(transport.is_connected)

    def test_is_connected_after_disconnect(self):
        """Test is_connected after disconnecting."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.disconnect()
        self.assertFalse(transport.is_connected)

    def test_local_node_id_before_connect(self):
        """Test local_node_id before connecting."""
        transport = MeshtasticSerialTransport()
        self.assertIsNone(transport.local_node_id)

    def test_local_node_id_after_connect(self):
        """Test local_node_id after connecting."""
        mock_iface = MockSerialInterface(0xAABBCCDD)
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        self.assertEqual(transport.local_node_id, "!aabbccdd")

    def test_local_node_id_after_disconnect(self):
        """Test local_node_id after disconnecting."""
        mock_iface = MockSerialInterface()
        self.mock_meshtastic.serial_interface.SerialInterface.return_value = mock_iface

        transport = MeshtasticSerialTransport()
        transport.connect()
        transport.disconnect()
        self.assertIsNone(transport.local_node_id)


if __name__ == "__main__":
    unittest.main()
