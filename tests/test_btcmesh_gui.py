#!/usr/bin/env python3
"""
Unit tests for btcmesh_gui.py

Tests the GUI logic, organized by story number from project/tasks.txt.
"""
import sys
import unittest
import unittest.mock
import queue
import logging

# Mock Kivy modules before importing btcmesh_gui
# This is necessary because Python loads the entire module (including Kivy imports)
# before extracting the specific functions we want to test
# These mocks are needed to also be able to run the tests in an environment
# without Kivy installed (like a CI server), otherwise they would fail.

# Create proper base classes for Kivy widgets to allow class inheritance
class MockCanvas:
    """Mock canvas for Kivy widgets."""
    def __init__(self):
        self.before = MockCanvasContext()


class MockCanvasContext:
    """Mock canvas context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockBoxLayout:
    """Mock base class for BoxLayout to allow proper class inheritance."""
    def __init__(self, **kwargs):
        self.canvas = MockCanvas()
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = 100

    def add_widget(self, widget):
        pass

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockScrollView:
    """Mock base class for ScrollView."""
    def __init__(self, **kwargs):
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = 100

    def add_widget(self, widget):
        pass

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockApp:
    """Mock base class for App."""
    def __init__(self, **kwargs):
        pass

    def run(self):
        pass


kivy_mock = unittest.mock.MagicMock()
# get_color_from_hex should return a tuple like (r, g, b, a)
kivy_mock.get_color_from_hex = lambda _: (1, 1, 1, 1)

# Set up modules with proper base classes for inheritance
boxlayout_mock = unittest.mock.MagicMock()
boxlayout_mock.BoxLayout = MockBoxLayout

scrollview_mock = unittest.mock.MagicMock()
scrollview_mock.ScrollView = MockScrollView

app_mock = unittest.mock.MagicMock()
app_mock.App = MockApp

# Properties need to return actual values, not MagicMocks
properties_mock = unittest.mock.MagicMock()
properties_mock.StringProperty = lambda default='': default
properties_mock.BooleanProperty = lambda default=False: default

sys.modules['kivy'] = kivy_mock
sys.modules['kivy.app'] = app_mock
sys.modules['kivy.uix'] = kivy_mock
sys.modules['kivy.uix.boxlayout'] = boxlayout_mock
sys.modules['kivy.uix.label'] = kivy_mock
sys.modules['kivy.uix.textinput'] = kivy_mock
sys.modules['kivy.uix.button'] = kivy_mock
sys.modules['kivy.uix.scrollview'] = scrollview_mock
sys.modules['kivy.uix.popup'] = kivy_mock
sys.modules['kivy.uix.widget'] = kivy_mock
sys.modules['kivy.uix.togglebutton'] = kivy_mock
sys.modules['kivy.uix.spinner'] = kivy_mock
sys.modules['kivy.clock'] = kivy_mock
sys.modules['kivy.graphics'] = kivy_mock
sys.modules['kivy.core'] = kivy_mock
sys.modules['kivy.core.window'] = kivy_mock
sys.modules['kivy.core.clipboard'] = kivy_mock
sys.modules['kivy.properties'] = properties_mock
sys.modules['kivy.utils'] = kivy_mock

# Mock pubsub (used by btcmesh_cli)
pubsub_mock = unittest.mock.MagicMock()
sys.modules['pubsub'] = pubsub_mock

# Mock meshtastic (for device scanning tests)
meshtastic_mock = unittest.mock.MagicMock()
meshtastic_mock.util = unittest.mock.MagicMock()
meshtastic_mock.util.blacklistVids = []
meshtastic_mock.util.eliminate_duplicate_port = lambda ports: ports
sys.modules['meshtastic'] = meshtastic_mock
sys.modules['meshtastic.util'] = meshtastic_mock.util
sys.modules['meshtastic.serial_interface'] = unittest.mock.MagicMock()

# Default serial port enumeration to "no devices" so tests that don't scan
# explicitly aren't affected by whatever hardware happens to be attached to
# the machine running the suite; per-test patches override this as needed.
unittest.mock.patch('serial.tools.list_ports.comports', return_value=[]).start()

from btcmesh_gui import (
    get_log_color,
    get_print_color,
    process_result,
    validate_send_inputs,
    ResultAction,
    scan_meshtastic_devices,
    NO_DEVICES_TEXT,
    SCANNING_TEXT,
    SELECT_DEVICE_TEXT,
    CONNECT_MAX_ATTEMPTS,
    NO_NODES_TEXT,
    MANUAL_ENTRY_TEXT,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_SUCCESS,
    COLOR_PRIMARY,
    COLOR_SECUNDARY,
    COLOR_DISCONNECTED,
    ConnectionState,
    STATE_DISCONNECTED,
    STATE_CONNECTION_FAILED,
    STATE_CONNECTION_ERROR,
)


# =============================================================================
# Story 9.1: Implement Send Transaction Button
# Tests for input validation before sending transactions
# =============================================================================

class TestSendButtonValidationStory91(unittest.TestCase):
    """Tests for validate_send_inputs() - Story 9.1: Send Transaction Button."""

    def test_empty_destination_returns_error(self):
        """Given empty destination, Then returns error message."""
        result = validate_send_inputs("", "aabbccdd", True)
        self.assertEqual(result, "Enter destination node ID")

    def test_destination_without_exclamation_returns_error(self):
        """Given destination without '!', Then returns error message."""
        result = validate_send_inputs("abc123", "aabbccdd", True)
        self.assertEqual(result, "Destination must start with '!'")

    def test_empty_tx_hex_returns_error(self):
        """Given empty tx_hex, Then returns error message."""
        result = validate_send_inputs("!abc123", "", True)
        self.assertEqual(result, "Enter transaction hex")

    def test_odd_length_tx_hex_returns_error(self):
        """Given tx_hex with odd length, Then returns error message."""
        result = validate_send_inputs("!abc123", "aabbccd", True)
        self.assertEqual(result, "Hex must have even length")

    def test_invalid_hex_characters_returns_error(self):
        """Given tx_hex with invalid characters, Then returns error message."""
        result = validate_send_inputs("!abc123", "gghhiijj", True)
        self.assertEqual(result, "Invalid hex characters")

    def test_no_interface_returns_error(self):
        """Given no Meshtastic interface, Then returns error message."""
        result = validate_send_inputs("!abc123", "aabbccdd", False)
        self.assertEqual(result, "Meshtastic not connected")

    def test_valid_inputs_returns_none(self):
        """Given all valid inputs, Then returns None."""
        result = validate_send_inputs("!abc123", "aabbccdd", True)
        self.assertIsNone(result)

    def test_validation_order_checks_dest_first(self):
        """Given multiple invalid inputs, Then checks destination first."""
        result = validate_send_inputs("", "", False)
        self.assertEqual(result, "Enter destination node ID")

    def test_validation_order_checks_dest_format_second(self):
        """Given invalid dest format and other errors, Then checks dest format second."""
        result = validate_send_inputs("abc", "", False)
        self.assertEqual(result, "Destination must start with '!'")

    def test_validation_order_checks_tx_hex_third(self):
        """Given empty tx_hex and no interface, Then checks tx_hex third."""
        result = validate_send_inputs("!abc123", "", False)
        self.assertEqual(result, "Enter transaction hex")

    def test_whitespace_only_destination_returns_error(self):
        """Given whitespace-only destination (after strip), Then returns error."""
        result = validate_send_inputs("", "aabbccdd", True)
        self.assertEqual(result, "Enter destination node ID")

    def test_dry_run_without_interface_returns_none(self):
        """Given dry_run=True and no Meshtastic interface, Then returns None (valid).

        Story 6.5: Dry run should work without Meshtastic connection.
        """
        result = validate_send_inputs("!abc123", "aabbccdd", False, dry_run=True)
        self.assertIsNone(result)

    def test_dry_run_still_validates_other_inputs(self):
        """Given dry_run=True but invalid hex, Then still returns error.

        Story 6.5: Dry run should still validate destination and tx_hex.
        """
        result = validate_send_inputs("!abc123", "gghhiijj", False, dry_run=True)
        self.assertEqual(result, "Invalid hex characters")

    def test_non_dry_run_without_interface_returns_error(self):
        """Given dry_run=False and no Meshtastic interface, Then returns error.

        Ensures regular mode still requires Meshtastic connection.
        """
        result = validate_send_inputs("!abc123", "aabbccdd", False, dry_run=False)
        self.assertEqual(result, "Meshtastic not connected")

    def test_destination_same_as_own_node_returns_error(self):
        """Given destination same as own node ID, Then returns error.

        Story 11.2: Cannot send transaction to yourself.
        """
        own_node_id = "!abcd1234"
        result = validate_send_inputs("!abcd1234", "aabbccdd", True, own_node_id=own_node_id)
        self.assertEqual(result, "Cannot send to your own node")

    def test_destination_different_from_own_node_returns_none(self):
        """Given destination different from own node ID, Then returns None (valid).

        Story 11.2: Sending to a different node should be allowed.
        """
        own_node_id = "!abcd1234"
        result = validate_send_inputs("!efef5678", "aabbccdd", True, own_node_id=own_node_id)
        self.assertIsNone(result)

    def test_own_node_id_none_skips_validation(self):
        """Given own_node_id is None, Then skips self-send validation.

        When not connected, we don't know our own node ID.
        """
        result = validate_send_inputs("!abcd1234", "aabbccdd", True, own_node_id=None)
        self.assertIsNone(result)

    def test_cli_finished_success_stops_sending(self):
        """Given 'cli_finished' with exit code 0, Then stops sending and shows success."""
        result = ('cli_finished', 0)

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('successfully', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_SUCCESS)

    def test_cli_finished_failure_stops_sending(self):
        """Given 'cli_finished' with non-zero exit code, Then stops sending and shows error."""
        result = ('cli_finished', 1)

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('1', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)


# =============================================================================
# Story 9.3: Implement Abort Button
# Tests for abort functionality
# =============================================================================

class TestAbortButtonStory93(unittest.TestCase):
    """Tests for abort result processing - Story 9.3: Abort Button."""

    def test_aborted_result_stops_sending(self):
        """Given 'aborted' result, Then stops sending and shows warning."""
        result = ('aborted',)

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('aborted', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_WARNING)


# =============================================================================
# Story 10.1: Implement Connection Status Display
# Tests for connection status result processing
# =============================================================================

class TestConnectionStatusStory101(unittest.TestCase):
    """Tests for connection result processing - Story 10.1: Connection Status Display."""

    def test_connected_result_sets_connection_info(self):
        """Given 'connected' result, Then sets connection text, color, and stores iface."""
        mock_iface = unittest.mock.MagicMock()
        result = ('connected', mock_iface, '!abc123')

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected (!abc123)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)
        self.assertEqual(action.store_iface, mock_iface)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Connected to Meshtastic device: !abc123', action.log_messages[0][0])

    def test_connection_failed_result(self):
        """Given 'connection_failed' result, Then sets error connection info."""
        result = ('connection_failed', None, None)

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connection failed')
        self.assertEqual(action.connection_color, COLOR_ERROR)
        self.assertEqual(len(action.log_messages), 1)
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_connection_error_result(self):
        """Given 'connection_error' result, Then includes error message."""
        result = ('connection_error', 'Device not found', None)

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Error')
        self.assertEqual(action.connection_color, COLOR_ERROR)
        self.assertIn('Device not found', action.log_messages[0][0])

    def test_connection_initializing_result(self):
        """Given 'connection_initializing' result, Then shows initializing message."""
        result = ('connection_initializing', 'Resource temporarily unavailable', None)

        action = process_result(result)

        # Should show initializing message (not error)
        self.assertIn('initializing', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_WARNING)
        # Should update connection status
        self.assertEqual(action.connection_text, 'Meshtastic: Initializing...')
        self.assertEqual(action.connection_color, COLOR_WARNING)


# =============================================================================
# Story 10.2: Implement Scrollable Status Log
# Tests for log message display, color coding, and message handling
# =============================================================================


# =============================================================================
# Story 10.3: Implement Success/Failure Popups
# Tests for popup triggering
# =============================================================================

class TestPopupsStory103(unittest.TestCase):
    """Tests for success/failure popup triggering - Story 10.3: Success/Failure Popups."""

    def test_tx_success_result_shows_popup(self):
        """Given 'tx_success' result, Then shows popup and success messages."""
        result = ('tx_success', 'abc123def456789')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertEqual(action.show_success_popup, 'abc123def456789')
        self.assertEqual(len(action.log_messages), 2)
        self.assertIn('successful', action.log_messages[0][0].lower())
        self.assertIn('abc123def456789', action.log_messages[1][0])

    def test_print_with_txid_success_triggers_popup(self):
        """Given 'print' result with CLI success message and TXID, Then shows popup."""
        # This is the actual message format from cli_main
        result = ('print', 'Transaction successfully broadcast by relay. TXID: abc123def456')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertEqual(action.show_success_popup, 'abc123def456')
        self.assertEqual(len(action.log_messages), 1)

    def test_print_with_txid_only_does_not_trigger_popup(self):
        """Given 'print' result with just TXID (no success), Then no popup."""
        # Just TXID without "successfully" should not trigger popup
        result = ('print', 'TXID: abc123def456')

        action = process_result(result)

        self.assertFalse(action.stop_sending)
        self.assertIsNone(action.show_success_popup)

    def test_error_result_stops_sending(self):
        """Given 'error' result, Then stops sending and shows error in log."""
        result = ('error', 'Something went wrong')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('Something went wrong', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)


# =============================================================================
# Story 22.2: TransactionSender Result Types
# Tests for TransactionSender result types (chunk_sending, progress, wire_sent, etc)
# =============================================================================

class TestTransactionSenderResultsStory222(unittest.TestCase):
    """Tests for TransactionSender result types - Story 22.2."""

    def test_chunk_sending_first_attempt(self):
        """Given chunk_sending result with attempt=1, Then shows 'Sending chunk X/Y...'."""
        result = ('chunk_sending', 1, 3, 1)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Sending chunk 1/3', action.log_messages[0][0])
        self.assertNotIn('retry', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)

    def test_chunk_sending_with_retry(self):
        """Given chunk_sending result with attempt=2, Then shows retry message."""
        result = ('chunk_sending', 2, 3, 2)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Sending chunk 2/3', action.log_messages[0][0])
        self.assertIn('retry 1', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)

    def test_chunk_sending_with_multiple_retries(self):
        """Given chunk_sending result with attempt=3, Then shows correct retry count."""
        result = ('chunk_sending', 1, 5, 3)

        action = process_result(result)

        self.assertIn('retry 2', action.log_messages[0][0])

    def test_wire_sent_shows_protocol_detail(self):
        """Given wire_sent result, Then shows arrow and wire format in secondary color."""
        wire_format = 'BTC_TX|abc123|1/3|020000...'
        result = ('wire_sent', wire_format)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('->', action.log_messages[0][0])
        self.assertIn(wire_format, action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_SECUNDARY)

    def test_progress_intermediate_chunk(self):
        """Given progress for chunk 2 of 3, Then shows 'Chunk 2/3 sent'."""
        result = ('progress', 2, 3)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertEqual(action.log_messages[0][0], 'Chunk 2/3 sent')
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)
        self.assertFalse(action.stop_sending)

    def test_progress_final_chunk(self):
        """Given progress for final chunk, Then shows waiting message."""
        result = ('progress', 3, 3)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('waiting for broadcast', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)
        self.assertFalse(action.stop_sending)

    def test_wire_received_shows_incoming_message(self):
        """Given wire_received result, Then shows arrow and message in secondary color."""
        message = 'BTC_CHUNK_ACK|abc123|2|REQUEST_CHUNK|3'
        result = ('wire_received', message)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('<-', action.log_messages[0][0])
        self.assertIn(message, action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_SECUNDARY)

    def test_send_result_success_shows_popup(self):
        """Given send_result with success=True, Then shows popup and stops sending."""
        from client.sender import SendResult
        txid = 'abc123def456789'
        result = ('send_result', SendResult(success=True, session_id='sess1', txid=txid))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertEqual(action.show_success_popup, txid)
        self.assertEqual(len(action.log_messages), 0)  # No error message

    def test_send_result_error_shows_message(self):
        """Given send_result with error, Then shows error message and stops sending."""
        from client.sender import SendResult
        result = ('send_result', SendResult(
            success=False,
            session_id='sess1',
            error='Insufficient fee'
        ))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Insufficient fee', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_send_result_aborted_by_user(self):
        """Given send_result with abort, Then shows abort message."""
        from client.sender import SendResult
        result = ('send_result', SendResult(
            success=False,
            session_id='sess1',
            error='Aborted by user'
        ))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('aborted', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_WARNING)



# Story 11.1: Device Selection Dropdown
# Tests for Meshtastic device scanning and selection
# =============================================================================

class TestDeviceSelectionStory111(unittest.TestCase):
    """Tests for device selection dropdown - Story 11.1: Device Selection Dropdown."""

    def test_scan_handles_import_error(self):
        """Given serial port enumeration fails to import, Then returns empty list."""
        with unittest.mock.patch('serial.tools.list_ports.comports', side_effect=ImportError):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_empty_list_on_exception(self):
        """Given comports raises exception, Then returns empty list."""
        with unittest.mock.patch('serial.tools.list_ports.comports', side_effect=Exception("Test error")):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_device_list(self):
        """Given comports returns non-blacklisted devices, Then returns those devices."""
        mock_ports = [
            unittest.mock.MagicMock(device='/dev/ttyACM0', vid=0x303a),
            unittest.mock.MagicMock(device='/dev/ttyUSB0', vid=0x2886),
        ]
        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = scan_meshtastic_devices()
            self.assertEqual(result, ['/dev/ttyACM0', '/dev/ttyUSB0'])

    def test_scan_returns_empty_list_when_no_devices(self):
        """Given comports returns empty list, Then returns empty list."""
        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=[]):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_no_devices_text_constant(self):
        """Verify NO_DEVICES_TEXT constant is defined correctly."""
        self.assertEqual(NO_DEVICES_TEXT, "No devices found")

    def test_scanning_text_constant(self):
        """Verify SCANNING_TEXT constant is defined correctly."""
        self.assertEqual(SCANNING_TEXT, "Scanning...")


# =============================================================================
# Device connection retry + first-device-selection fixes
# Tests for issues found while testing the scan_meshtastic_devices() fix:
# a transient connect error left the GUI stuck forever, and the first device
# in a multi-device list couldn't be selected until a different device was
# picked first (see project/issues.txt Issue 10/11).
# =============================================================================

class TestDeviceConnectionRetryAndSelectionFix(unittest.TestCase):
    """Tests for connection retry logic and multi-device placeholder text."""

    class _ImmediateThread:
        """Runs the thread target synchronously instead of actually threading,
        so tests stay deterministic and don't need real background threads."""

        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    def _drain(self, q):
        results = []
        while not q.empty():
            results.append(q.get_nowait())
        return results

    def test_init_meshtastic_retries_transient_error_then_succeeds(self):
        """Given a transient error on the first attempt and success on the
        second, Then it retries instead of giving up immediately."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.status_log = unittest.mock.MagicMock()

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0x12345678

        failing_transport = unittest.mock.MagicMock()
        failing_transport.connect.side_effect = Exception("Resource temporarily unavailable")

        succeeding_transport = unittest.mock.MagicMock()
        succeeding_transport.connect.return_value = None
        succeeding_transport._iface = mock_iface

        transports = [failing_transport, succeeding_transport]

        with unittest.mock.patch('btcmesh_gui.MeshtasticSerialTransport', side_effect=transports), \
             unittest.mock.patch('btcmesh_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch('btcmesh_gui.time.sleep'), \
             unittest.mock.patch('btcmesh_gui.get_own_node_name', return_value='TestNode'):
            btcmesh_gui.BTCMeshGUI._init_meshtastic(gui, port='/dev/ttyFake')

        result_types = [r[0] for r in self._drain(gui.result_queue)]
        self.assertEqual(result_types.count('connection_initializing'), 1)
        self.assertIn('connected', result_types)
        self.assertIn('transport_ready', result_types)

    def test_init_meshtastic_gives_up_after_max_attempts(self):
        """Given a persistently transient error, Then after CONNECT_MAX_ATTEMPTS
        it reports connection_error instead of hanging forever (regression
        test for the GUI getting permanently stuck on 'Device is
        initializing, please wait...')."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.status_log = unittest.mock.MagicMock()

        always_failing_transport = unittest.mock.MagicMock()
        always_failing_transport.connect.side_effect = Exception("Resource temporarily unavailable")

        with unittest.mock.patch('btcmesh_gui.MeshtasticSerialTransport', return_value=always_failing_transport), \
             unittest.mock.patch('btcmesh_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch('btcmesh_gui.time.sleep'):
            btcmesh_gui.BTCMeshGUI._init_meshtastic(gui, port='/dev/ttyFake')

        results = self._drain(gui.result_queue)
        result_types = [r[0] for r in results]

        self.assertEqual(always_failing_transport.connect.call_count, CONNECT_MAX_ATTEMPTS)
        self.assertEqual(result_types.count('connection_initializing'), CONNECT_MAX_ATTEMPTS)
        self.assertEqual(result_types[-1], 'connection_error')

    def test_devices_found_multiple_sets_placeholder_not_first_device(self):
        """Given multiple devices found, Then the spinner's displayed text is
        a placeholder distinct from any real device path (not devices[0]) -
        Kivy Spinner only fires its text-change event when the value actually
        changes, so reusing devices[0] as the placeholder silently prevented
        selecting the first device until a different one was picked first."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()

        devices = ['/dev/ttyUSB0', '/dev/ttyACM0']
        btcmesh_gui.BTCMeshGUI._handle_result(gui, ('devices_found', devices))

        self.assertEqual(gui.device_spinner.values, devices)
        self.assertEqual(gui.device_spinner.text, SELECT_DEVICE_TEXT)
        self.assertNotIn(gui.device_spinner.text, devices)

    def test_on_device_selected_ignores_placeholder_text(self):
        """Given the multi-device placeholder text, Then on_device_selected
        does nothing (no connection attempt)."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._disconnect_device = unittest.mock.MagicMock()
        gui._init_meshtastic = unittest.mock.MagicMock()

        btcmesh_gui.BTCMeshGUI.on_device_selected(gui, None, SELECT_DEVICE_TEXT)

        gui._disconnect_device.assert_not_called()
        gui._init_meshtastic.assert_not_called()


# =============================================================================
# Story 11.2: Known Nodes Dropdown for Destination
# Tests for extracting and formatting known nodes from Meshtastic interface
# =============================================================================

class TestKnownNodesStory112(unittest.TestCase):
    """Tests for known nodes dropdown - Story 11.2."""

    def _create_mock_node(self, node_id, long_name, short_name, last_heard, hops_away=1):
        """Helper to create a mock node structure."""
        return {
            'user': {
                'id': node_id,
                'longName': long_name,
                'shortName': short_name,
            },
            'lastHeard': last_heard,
            'hopsAway': hops_away,
        }

    def test_get_known_nodes_returns_empty_list_when_no_nodes(self):
        """Given interface has no nodes, Then returns empty list."""
        from btcmesh_gui import get_known_nodes
        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = {}
        mock_iface.myInfo.my_node_num = 12345678

        result = get_known_nodes(mock_iface)

        self.assertEqual(result, [])

    def test_get_known_nodes_returns_empty_list_when_nodes_is_none(self):
        """Given interface.nodes is None, Then returns empty list."""
        from btcmesh_gui import get_known_nodes
        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = None
        mock_iface.myInfo.my_node_num = 12345678

        result = get_known_nodes(mock_iface)

        self.assertEqual(result, [])

    def test_get_known_nodes_extracts_node_info(self):
        """Given interface has nodes, Then extracts id, name, lastHeard."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'Node One', 'NO1', now - 100),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!abcd1234')
        self.assertEqual(result[0]['name'], 'Node One')
        self.assertEqual(result[0]['lastHeard'], now - 100)

    def test_get_known_nodes_filters_out_own_node(self):
        """Given interface has own node in list, Then filters it out."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234  # Own node
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'My Node', 'MYN', now - 100),
            '!efef5678': self._create_mock_node('!efef5678', 'Other Node', 'OTH', now - 200),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!efef5678')

    def test_get_known_nodes_sorts_by_last_heard_descending(self):
        """Given multiple nodes, Then sorts by lastHeard (most recent first)."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!oldest00': self._create_mock_node('!oldest00', 'Oldest', 'OLD', now - 3600),
            '!newest00': self._create_mock_node('!newest00', 'Newest', 'NEW', now - 60),
            '!middle00': self._create_mock_node('!middle00', 'Middle', 'MID', now - 1800),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['id'], '!newest00')  # Most recent
        self.assertEqual(result[1]['id'], '!middle00')
        self.assertEqual(result[2]['id'], '!oldest00')  # Oldest

    def test_get_known_nodes_uses_short_name_if_no_long_name(self):
        """Given node has no longName, Then uses shortName."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': 'SHRT',
                },
                'lastHeard': now - 100,
                'hopsAway': 1,
            },
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(result[0]['name'], 'SHRT')

    def test_get_known_nodes_handles_missing_user_info(self):
        """Given node has no user info, Then handles gracefully."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': {
                'lastHeard': now - 100,
            },
        }

        result = get_known_nodes(mock_iface)

        # Should still include node but with node_id as name
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!abcd1234')

    def test_get_known_nodes_includes_is_recent_flag(self):
        """Given nodes with different lastHeard, Then includes is_recent flag."""
        from btcmesh_gui import get_known_nodes
        import time
        now = int(time.time())
        hours_24 = 24 * 60 * 60

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!recent00': self._create_mock_node('!recent00', 'Recent', 'REC', now - 100),
            '!stale000': self._create_mock_node('!stale000', 'Stale', 'STL', now - hours_24 - 100),
        }

        result = get_known_nodes(mock_iface)

        recent_node = next(n for n in result if n['id'] == '!recent00')
        stale_node = next(n for n in result if n['id'] == '!stale000')

        self.assertTrue(recent_node['is_recent'])
        self.assertFalse(stale_node['is_recent'])

    def test_format_node_display_recent_node(self):
        """Given a recent node, Then displays name and id."""
        from btcmesh_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'Test Node', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertEqual(result, 'Test Node (!abcd1234)')

    def test_format_node_display_stale_node(self):
        """Given a stale node, Then displays name and id (same as recent)."""
        from btcmesh_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'Test Node', 'lastHeard': 123456, 'is_recent': False}

        result = format_node_display(node)

        self.assertEqual(result, 'Test Node (!abcd1234)')

    def test_format_node_display_includes_name_and_id(self):
        """Given a node, Then includes name and id in display."""
        from btcmesh_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'My Relay', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertIn('My Relay', result)
        self.assertIn('!abcd1234', result)

    def test_format_node_display_format(self):
        """Given a node, Then formats as 'name (id)'."""
        from btcmesh_gui import format_node_display
        node = {'id': '!efef5678', 'name': 'Relay Server', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertEqual(result, 'Relay Server (!efef5678)')

    def test_no_nodes_text_constant(self):
        """Verify NO_NODES_TEXT constant is defined correctly."""
        self.assertEqual(NO_NODES_TEXT, "No nodes found")

    def test_manual_entry_text_constant(self):
        """Verify MANUAL_ENTRY_TEXT constant is defined correctly."""
        self.assertEqual(MANUAL_ENTRY_TEXT, "Enter manually...")


# =============================================================================
# Story 11.3: Display Connected Device Name
# Tests for displaying the connected device's name in the connection status
# =============================================================================

class TestDisplayDeviceNameStory113(unittest.TestCase):
    """Tests for displaying connected device name - Story 11.3."""

    def _create_mock_node(self, node_id, long_name, short_name):
        """Helper to create a mock node structure."""
        return {
            'user': {
                'id': node_id,
                'longName': long_name,
                'shortName': short_name,
            },
        }

    def test_get_own_node_name_returns_long_name(self):
        """Given interface has own node with longName, Then returns longName."""
        from btcmesh_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'My Device', 'MYDEV'),
        }

        result = get_own_node_name(mock_iface)

        self.assertEqual(result, 'My Device')

    def test_get_own_node_name_returns_short_name_if_no_long_name(self):
        """Given interface has own node without longName, Then returns shortName."""
        from btcmesh_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': 'SHRT',
                },
            },
        }

        result = get_own_node_name(mock_iface)

        self.assertEqual(result, 'SHRT')

    def test_get_own_node_name_returns_none_if_no_name(self):
        """Given interface has own node without any name, Then returns None."""
        from btcmesh_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': '',
                },
            },
        }

        result = get_own_node_name(mock_iface)

        self.assertIsNone(result)

    def test_get_own_node_name_returns_none_if_no_interface(self):
        """Given no interface, Then returns None."""
        from btcmesh_gui import get_own_node_name

        result = get_own_node_name(None)

        self.assertIsNone(result)

    def test_get_own_node_name_returns_none_if_own_node_not_in_nodes(self):
        """Given own node not in nodes dict, Then returns None."""
        from btcmesh_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {}

        result = get_own_node_name(mock_iface)

        self.assertIsNone(result)

    def test_connected_with_node_name_shows_name_in_status(self):
        """Given 'connected' with node_name, Then shows name in status."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', 'My Device')

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected - My Device (!abcd1234)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)

    def test_connected_without_node_name_shows_only_id(self):
        """Given 'connected' without node_name, Then shows only id."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', None)

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected (!abcd1234)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)

    def test_connected_log_message_includes_name(self):
        """Given 'connected' with node_name, Then log message includes name."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', 'My Device')

        action = process_result(result)

        self.assertIn('My Device', action.log_messages[0][0])
        self.assertIn('!abcd1234', action.log_messages[0][0])


# =============================================================================
# Story 9.5: Disable Controls During Transaction Send
# Tests for disabling input controls during sending and re-enabling on completion
# =============================================================================

class TestDisableControlsStory95(unittest.TestCase):
    """Tests for disabling controls during transaction send - Story 9.5.

    These tests verify:
    1. process_result() sets stop_sending correctly for different result types
    2. _handle_result() calls _set_controls_enabled(True) when stop_sending is True
    3. on_send_pressed() calls _set_controls_enabled(False) when starting to send
    """

    def test_handle_result_calls_set_controls_enabled_true_on_cli_finished(self):
        """Given 'cli_finished' result, Then _handle_result calls _set_controls_enabled(True)."""
        # Import the unbound function from the module
        import btcmesh_gui

        # Create a mock GUI instance with all required attributes
        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        # Call the actual _handle_result method with our mock as 'self'
        btcmesh_gui.BTCMeshGUI._handle_result(gui, ('cli_finished', 0))

        # Verify _set_controls_enabled was called with True
        gui._set_controls_enabled.assert_called_once_with(True)

    def test_handle_result_calls_set_controls_enabled_true_on_error(self):
        """Given 'error' result, Then _handle_result calls _set_controls_enabled(True)."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        btcmesh_gui.BTCMeshGUI._handle_result(gui, ('error', 'Something failed'))

        gui._set_controls_enabled.assert_called_once_with(True)

    def test_handle_result_calls_set_controls_enabled_true_on_abort(self):
        """Given 'aborted' result, Then _handle_result calls _set_controls_enabled(True)."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        btcmesh_gui.BTCMeshGUI._handle_result(gui, ('aborted',))

        gui._set_controls_enabled.assert_called_once_with(True)

    def test_handle_result_does_not_call_set_controls_enabled_on_log(self):
        """Given 'log' result, Then _handle_result does NOT call _set_controls_enabled."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        btcmesh_gui.BTCMeshGUI._handle_result(gui, ('log', 'Progress', logging.INFO))

        gui._set_controls_enabled.assert_not_called()

    def test_on_send_pressed_calls_set_controls_enabled_false(self):
        """Given valid inputs, Then on_send_pressed calls _set_controls_enabled(False)."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui._get_own_node_id = unittest.mock.MagicMock(return_value='!12345678')
        gui.dest_input.text = '!abcd1234'
        gui.tx_input.text = 'aabbccdd'
        gui.dry_run_toggle.state = 'normal'
        gui.iface = unittest.mock.MagicMock()
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.is_sending = False
        gui.abort_requested = False

        # Mock threading to prevent actual thread start
        with unittest.mock.patch('threading.Thread'):
            btcmesh_gui.BTCMeshGUI.on_send_pressed(gui, None)

        # Verify _set_controls_enabled was called with False
        gui._set_controls_enabled.assert_called_once_with(False)

    def test_on_send_pressed_does_not_call_set_controls_enabled_on_validation_error(self):
        """Given invalid inputs, Then on_send_pressed does NOT call _set_controls_enabled."""
        import btcmesh_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui._get_own_node_id = unittest.mock.MagicMock(return_value='!12345678')
        gui.dest_input.text = ''  # Invalid: empty destination
        gui.tx_input.text = 'aabbccdd'
        gui.dry_run_toggle.state = 'normal'
        gui.iface = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui._init_meshtastic = unittest.mock.MagicMock()

        btcmesh_gui.BTCMeshGUI.on_send_pressed(gui, None)

        # Verify _set_controls_enabled was NOT called (validation failed)
        gui._set_controls_enabled.assert_not_called()

    def test_process_result_stop_sending_true_for_completion_results(self):
        """Verify process_result sets stop_sending=True for completion results."""
        completion_results = [
            ('cli_finished', 0),
            ('cli_finished', 1),
            ('error', 'Failed'),
            ('aborted',),
            ('tx_success', 'txid123'),
        ]

        for result in completion_results:
            action = process_result(result)
            self.assertTrue(action.stop_sending, f"stop_sending should be True for {result}")

    def test_process_result_stop_sending_false_for_progress_results(self):
        """Verify process_result sets stop_sending=False for progress results."""
        progress_results = [
            ('log', 'Progress', logging.INFO),
            ('print', 'Some output'),
            ('connected', unittest.mock.MagicMock(), '!abc123'),
        ]

        for result in progress_results:
            action = process_result(result)
            self.assertFalse(action.stop_sending, f"stop_sending should be False for {result}")


if __name__ == '__main__':
    unittest.main()
