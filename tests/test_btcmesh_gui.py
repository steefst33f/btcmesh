#!/usr/bin/env python3
"""
Unit tests for btcmesh_gui.py

Tests the GUI logic.
"""
import unittest
import unittest.mock
import queue
import logging
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock Kivy modules before importing btcmesh_gui
sys.modules['kivy'] = unittest.mock.MagicMock()
sys.modules['kivy.app'] = unittest.mock.MagicMock()
sys.modules['kivy.uix'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.boxlayout'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.label'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.textinput'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.button'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.scrollview'] = unittest.mock.MagicMock()
sys.modules['kivy.uix.popup'] = unittest.mock.MagicMock()
sys.modules['kivy.clock'] = unittest.mock.MagicMock()
sys.modules['kivy.core'] = unittest.mock.MagicMock()
sys.modules['kivy.core.window'] = unittest.mock.MagicMock()
sys.modules['kivy.properties'] = unittest.mock.MagicMock()
sys.modules['kivy.utils'] = unittest.mock.MagicMock()

from btcmesh_gui import QueueLogHandler


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


if __name__ == '__main__':
    unittest.main()
