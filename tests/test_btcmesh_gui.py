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
kivy_mock = unittest.mock.MagicMock()
# get_color_from_hex should return a tuple like (r, g, b, a)
kivy_mock.get_color_from_hex = lambda _: (1, 1, 1, 1)
sys.modules['kivy'] = kivy_mock
sys.modules['kivy.app'] = kivy_mock
sys.modules['kivy.uix'] = kivy_mock
sys.modules['kivy.uix.boxlayout'] = kivy_mock
sys.modules['kivy.uix.label'] = kivy_mock
sys.modules['kivy.uix.textinput'] = kivy_mock
sys.modules['kivy.uix.button'] = kivy_mock
sys.modules['kivy.uix.scrollview'] = kivy_mock
sys.modules['kivy.uix.popup'] = kivy_mock
sys.modules['kivy.uix.widget'] = kivy_mock
sys.modules['kivy.uix.togglebutton'] = kivy_mock
sys.modules['kivy.uix.spinner'] = kivy_mock
sys.modules['kivy.clock'] = kivy_mock
sys.modules['kivy.graphics'] = kivy_mock
sys.modules['kivy.core'] = kivy_mock
sys.modules['kivy.core.window'] = kivy_mock
sys.modules['kivy.core.clipboard'] = kivy_mock
sys.modules['kivy.properties'] = kivy_mock
sys.modules['kivy.utils'] = kivy_mock

# Mock pubsub (used by btcmesh_cli)
pubsub_mock = unittest.mock.MagicMock()
sys.modules['pubsub'] = pubsub_mock

# Mock meshtastic (for device scanning tests)
meshtastic_mock = unittest.mock.MagicMock()
meshtastic_mock.util = unittest.mock.MagicMock()
meshtastic_mock.util.findPorts = unittest.mock.MagicMock(return_value=[])
sys.modules['meshtastic'] = meshtastic_mock
sys.modules['meshtastic.util'] = meshtastic_mock.util
sys.modules['meshtastic.serial_interface'] = unittest.mock.MagicMock()

from btcmesh_gui import (
    QueueLogHandler,
    get_log_color,
    get_print_color,
    process_result,
    validate_send_inputs,
    ResultAction,
    scan_meshtastic_devices,
    NO_DEVICES_TEXT,
    SCANNING_TEXT,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_SUCCESS,
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


# =============================================================================
# Story 10.2: Implement Scrollable Status Log
# Tests for log message display, color coding, and message handling
# =============================================================================

class TestStatusLogStory102(unittest.TestCase):
    """Tests for scrollable status log - Story 10.2: Scrollable Status Log."""

    def setUp(self):
        """Set up test fixtures for QueueLogHandler tests."""
        self.result_queue = queue.Queue()
        self.handler = QueueLogHandler(self.result_queue)
        self.handler.setFormatter(logging.Formatter('%(message)s'))

    # --- QueueLogHandler tests (log messages flow to status log) ---

    def test_queue_handler_emit_info_message(self):
        """Given an INFO log record, Then it should be added to the queue with correct level."""
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test info message',
            args=(),
            exc_info=None
        )

        self.handler.emit(record)

        self.assertFalse(self.result_queue.empty())
        result = self.result_queue.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test info message')
        self.assertEqual(result[2], logging.INFO)

    def test_queue_handler_emit_error_message(self):
        """Given an ERROR log record, Then it should be added to the queue with ERROR level."""
        record = logging.LogRecord(
            name='test',
            level=logging.ERROR,
            pathname='test.py',
            lineno=1,
            msg='Test error message',
            args=(),
            exc_info=None
        )

        self.handler.emit(record)

        result = self.result_queue.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test error message')
        self.assertEqual(result[2], logging.ERROR)

    def test_queue_handler_emit_warning_message(self):
        """Given a WARNING log record, Then it should be added to the queue with WARNING level."""
        record = logging.LogRecord(
            name='test',
            level=logging.WARNING,
            pathname='test.py',
            lineno=1,
            msg='Test warning message',
            args=(),
            exc_info=None
        )

        self.handler.emit(record)

        result = self.result_queue.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test warning message')
        self.assertEqual(result[2], logging.WARNING)

    def test_queue_handler_emit_with_format_args(self):
        """Given a log record with format arguments, Then the message should be formatted."""
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Chunk %d of %d sent',
            args=(3, 10),
            exc_info=None
        )

        self.handler.emit(record)

        result = self.result_queue.get_nowait()
        self.assertEqual(result[1], 'Chunk 3 of 10 sent')

    def test_queue_handler_logger_integration(self):
        """Given a logger with QueueLogHandler, Then log messages should appear in queue."""
        logger = logging.getLogger('test_gui_logger')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(self.handler)

        logger.info('Test message from logger')

        result = self.result_queue.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test message from logger')

    # --- ResultAction tests (result processing for log display) ---

    def test_result_action_default_values(self):
        """Given no arguments, Then ResultAction has correct defaults."""
        action = ResultAction()

        self.assertIsNone(action.connection_text)
        self.assertIsNone(action.connection_color)
        self.assertEqual(action.log_messages, [])
        self.assertFalse(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertIsNone(action.store_iface)

    def test_result_action_log_messages_mutable_default(self):
        """Given two ResultAction instances, Then they have separate log_messages lists."""
        action1 = ResultAction()
        action2 = ResultAction()

        action1.log_messages.append(('test', None))

        self.assertEqual(len(action1.log_messages), 1)
        self.assertEqual(len(action2.log_messages), 0)

    def test_unknown_result_type_returns_empty_action(self):
        """Given unknown result type, Then returns action with no changes."""
        result = ('unknown_type', 'data')

        action = process_result(result)

        self.assertIsNone(action.connection_text)
        self.assertIsNone(action.connection_color)
        self.assertEqual(len(action.log_messages), 0)
        self.assertFalse(action.stop_sending)
        self.assertIsNone(action.show_success_popup)

    # --- get_log_color tests (color coding for log messages) ---

    def test_error_level_returns_error_color(self):
        """Given ERROR level, Then returns COLOR_ERROR regardless of message."""
        result = get_log_color(logging.ERROR, "some message")
        self.assertEqual(result, COLOR_ERROR)

    def test_critical_level_returns_error_color(self):
        """Given CRITICAL level, Then returns COLOR_ERROR."""
        result = get_log_color(logging.CRITICAL, "critical issue")
        self.assertEqual(result, COLOR_ERROR)

    def test_warning_level_returns_warning_color(self):
        """Given WARNING level, Then returns COLOR_WARNING."""
        result = get_log_color(logging.WARNING, "warning message")
        self.assertEqual(result, COLOR_WARNING)

    def test_info_with_success_keyword_returns_success_color(self):
        """Given INFO level with 'success' in message, Then returns COLOR_SUCCESS."""
        result = get_log_color(logging.INFO, "Transaction success")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_info_with_ack_keyword_returns_success_color(self):
        """Given INFO level with 'ack' in message, Then returns COLOR_SUCCESS."""
        result = get_log_color(logging.INFO, "Received ACK from node")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_info_without_keywords_returns_none(self):
        """Given INFO level without success keywords, Then returns None."""
        result = get_log_color(logging.INFO, "Processing transaction")
        self.assertIsNone(result)

    def test_debug_without_keywords_returns_none(self):
        """Given DEBUG level without success keywords, Then returns None."""
        result = get_log_color(logging.DEBUG, "Debug info")
        self.assertIsNone(result)

    def test_log_color_case_insensitive_success_detection(self):
        """Given message with 'SUCCESS' uppercase, Then returns COLOR_SUCCESS."""
        result = get_log_color(logging.INFO, "Operation SUCCESS")
        self.assertEqual(result, COLOR_SUCCESS)

    # --- get_print_color tests (color coding for print output) ---

    def test_print_error_keyword_returns_error_color(self):
        """Given message with 'error', Then returns COLOR_ERROR."""
        result = get_print_color("An error occurred")
        self.assertEqual(result, COLOR_ERROR)

    def test_print_failed_keyword_returns_error_color(self):
        """Given message with 'failed', Then returns COLOR_ERROR."""
        result = get_print_color("Transaction failed")
        self.assertEqual(result, COLOR_ERROR)

    def test_print_abort_keyword_returns_error_color(self):
        """Given message with 'abort', Then returns COLOR_ERROR."""
        result = get_print_color("Aborting operation")
        self.assertEqual(result, COLOR_ERROR)

    def test_print_success_keyword_returns_success_color(self):
        """Given message with 'success', Then returns COLOR_SUCCESS."""
        result = get_print_color("Transaction success")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_print_txid_keyword_returns_success_color(self):
        """Given message with 'txid', Then returns COLOR_SUCCESS."""
        result = get_print_color("TXID: abc123def456")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_print_neutral_message_returns_none(self):
        """Given message without keywords, Then returns None."""
        result = get_print_color("Processing transaction")
        self.assertIsNone(result)

    def test_print_color_case_insensitive_error_detection(self):
        """Given message with 'ERROR' uppercase, Then returns COLOR_ERROR."""
        result = get_print_color("ERROR: something went wrong")
        self.assertEqual(result, COLOR_ERROR)

    def test_print_color_case_insensitive_success_detection(self):
        """Given message with 'SUCCESS' uppercase, Then returns COLOR_SUCCESS."""
        result = get_print_color("Operation SUCCESS")
        self.assertEqual(result, COLOR_SUCCESS)

    # --- process_result log/print color tests ---

    def test_log_result_with_error_level(self):
        """Given 'log' result with ERROR level, Then log message has error color."""
        result = ('log', 'An error occurred', logging.ERROR)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertEqual(action.log_messages[0][0], 'An error occurred')
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_log_result_with_warning_level(self):
        """Given 'log' result with WARNING level, Then log message has warning color."""
        result = ('log', 'A warning', logging.WARNING)

        action = process_result(result)

        self.assertEqual(action.log_messages[0][1], COLOR_WARNING)

    def test_log_result_with_success_keyword(self):
        """Given 'log' result with 'success' in message, Then has success color."""
        result = ('log', 'Transaction success', logging.INFO)

        action = process_result(result)

        self.assertEqual(action.log_messages[0][1], COLOR_SUCCESS)

    def test_print_result_with_error_keyword(self):
        """Given 'print' result with error keyword, Then has error color."""
        result = ('print', 'Error: something failed')

        action = process_result(result)

        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_print_result_with_txid_keyword(self):
        """Given 'print' result with 'txid', Then has success color."""
        result = ('print', 'TXID: abc123def456')

        action = process_result(result)

        self.assertEqual(action.log_messages[0][1], COLOR_SUCCESS)


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
# Story 11.1: Device Selection Dropdown
# Tests for Meshtastic device scanning and selection
# =============================================================================

class TestDeviceSelectionStory111(unittest.TestCase):
    """Tests for device selection dropdown - Story 11.1: Device Selection Dropdown."""

    def test_scan_handles_import_error(self):
        """Given meshtastic.util import fails, Then returns empty list."""
        with unittest.mock.patch('meshtastic.util.findPorts', side_effect=ImportError):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_empty_list_on_exception(self):
        """Given findPorts raises exception, Then returns empty list."""
        with unittest.mock.patch('meshtastic.util.findPorts', side_effect=Exception("Test error")):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_device_list(self):
        """Given findPorts returns devices, Then returns those devices."""
        mock_ports = ['/dev/ttyUSB0', '/dev/ttyACM0']
        with unittest.mock.patch('meshtastic.util.findPorts', return_value=mock_ports):
            result = scan_meshtastic_devices()
            self.assertEqual(result, mock_ports)

    def test_scan_returns_empty_list_when_no_devices(self):
        """Given findPorts returns empty list, Then returns empty list."""
        with unittest.mock.patch('meshtastic.util.findPorts', return_value=[]):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_empty_list_when_findports_returns_none(self):
        """Given findPorts returns None, Then returns empty list."""
        with unittest.mock.patch('meshtastic.util.findPorts', return_value=None):
            result = scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_no_devices_text_constant(self):
        """Verify NO_DEVICES_TEXT constant is defined correctly."""
        self.assertEqual(NO_DEVICES_TEXT, "No devices found")

    def test_scanning_text_constant(self):
        """Verify SCANNING_TEXT constant is defined correctly."""
        self.assertEqual(SCANNING_TEXT, "Scanning...")


if __name__ == '__main__':
    unittest.main()
