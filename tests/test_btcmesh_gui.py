#!/usr/bin/env python3
"""
Unit tests for btcmesh_gui.py

Tests the GUI logic.
"""
import unittest
import unittest.mock
import queue
import logging

from btcmesh_gui import (
    QueueLogHandler,
    get_log_color,
    get_print_color,
    process_result,
    validate_send_inputs,
    ResultAction,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_SUCCESS,
)


class TestQueueLogHandler(unittest.TestCase):
    """Tests for the QueueLogHandler class."""

    def setUp(self):
        """Set up test fixtures."""
        self.result_queue = queue.Queue()
        self.handler = QueueLogHandler(self.result_queue)
        self.handler.setFormatter(logging.Formatter('%(message)s'))

    def test_emit_info_message(self):
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

    def test_emit_error_message(self):
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

    def test_emit_warning_message(self):
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

    def test_emit_with_format_args(self):
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

    def test_logger_integration(self):
        """Given a logger with QueueLogHandler, Then log messages should appear in queue."""
        logger = logging.getLogger('test_gui_logger')
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(self.handler)

        logger.info('Test message from logger')

        result = self.result_queue.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test message from logger')


class TestGetLogColor(unittest.TestCase):
    """Tests for the get_log_color function."""

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

    def test_case_insensitive_success_detection(self):
        """Given message with 'SUCCESS' uppercase, Then returns COLOR_SUCCESS."""
        result = get_log_color(logging.INFO, "Operation SUCCESS")
        self.assertEqual(result, COLOR_SUCCESS)


class TestGetPrintColor(unittest.TestCase):
    """Tests for the get_print_color function."""

    def test_error_keyword_returns_error_color(self):
        """Given message with 'error', Then returns COLOR_ERROR."""
        result = get_print_color("An error occurred")
        self.assertEqual(result, COLOR_ERROR)

    def test_failed_keyword_returns_error_color(self):
        """Given message with 'failed', Then returns COLOR_ERROR."""
        result = get_print_color("Transaction failed")
        self.assertEqual(result, COLOR_ERROR)

    def test_abort_keyword_returns_error_color(self):
        """Given message with 'abort', Then returns COLOR_ERROR."""
        result = get_print_color("Aborting operation")
        self.assertEqual(result, COLOR_ERROR)

    def test_success_keyword_returns_success_color(self):
        """Given message with 'success', Then returns COLOR_SUCCESS."""
        result = get_print_color("Transaction success")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_txid_keyword_returns_success_color(self):
        """Given message with 'txid', Then returns COLOR_SUCCESS."""
        result = get_print_color("TXID: abc123def456")
        self.assertEqual(result, COLOR_SUCCESS)

    def test_neutral_message_returns_none(self):
        """Given message without keywords, Then returns None."""
        result = get_print_color("Processing transaction")
        self.assertIsNone(result)

    def test_case_insensitive_error_detection(self):
        """Given message with 'ERROR' uppercase, Then returns COLOR_ERROR."""
        result = get_print_color("ERROR: something went wrong")
        self.assertEqual(result, COLOR_ERROR)

    def test_case_insensitive_success_detection(self):
        """Given message with 'SUCCESS' uppercase, Then returns COLOR_SUCCESS."""
        result = get_print_color("Operation SUCCESS")
        self.assertEqual(result, COLOR_SUCCESS)


class TestProcessResult(unittest.TestCase):
    """Tests for the process_result function."""

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

    def test_cli_finished_success(self):
        """Given 'cli_finished' with exit code 0, Then shows success and stops sending."""
        result = ('cli_finished', 0)

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('successfully', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_SUCCESS)

    def test_cli_finished_failure(self):
        """Given 'cli_finished' with non-zero exit code, Then shows error."""
        result = ('cli_finished', 1)

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('1', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_tx_success_result(self):
        """Given 'tx_success' result, Then shows popup and success messages."""
        result = ('tx_success', 'abc123def456789')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertEqual(action.show_success_popup, 'abc123def456789')
        self.assertEqual(len(action.log_messages), 2)
        self.assertIn('successful', action.log_messages[0][0].lower())
        self.assertIn('abc123def456789', action.log_messages[1][0])

    def test_error_result(self):
        """Given 'error' result, Then shows failed popup and error message."""
        result = ('error', 'Something went wrong')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertTrue(action.show_failed_popup)
        self.assertIn('Something went wrong', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_unknown_result_type_returns_empty_action(self):
        """Given unknown result type, Then returns action with no changes."""
        result = ('unknown_type', 'data')

        action = process_result(result)

        self.assertIsNone(action.connection_text)
        self.assertIsNone(action.connection_color)
        self.assertEqual(len(action.log_messages), 0)
        self.assertFalse(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertFalse(action.show_failed_popup)


class TestResultAction(unittest.TestCase):
    """Tests for the ResultAction dataclass."""

    def test_default_values(self):
        """Given no arguments, Then ResultAction has correct defaults."""
        action = ResultAction()

        self.assertIsNone(action.connection_text)
        self.assertIsNone(action.connection_color)
        self.assertEqual(action.log_messages, [])
        self.assertFalse(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertFalse(action.show_failed_popup)
        self.assertIsNone(action.store_iface)

    def test_log_messages_mutable_default(self):
        """Given two ResultAction instances, Then they have separate log_messages lists."""
        action1 = ResultAction()
        action2 = ResultAction()

        action1.log_messages.append(('test', None))

        self.assertEqual(len(action1.log_messages), 1)
        self.assertEqual(len(action2.log_messages), 0)


class TestValidateSendInputs(unittest.TestCase):
    """Tests for the validate_send_inputs function."""

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
        # Note: The caller strips the input before calling validate_send_inputs
        result = validate_send_inputs("", "aabbccdd", True)
        self.assertEqual(result, "Enter destination node ID")


if __name__ == '__main__':
    unittest.main()
