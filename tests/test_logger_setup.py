"""Tests for core/logger_setup.py's set_logger_level() (Issue 49)."""
import logging
import unittest

from core.logger_setup import (
    LOG_FORMAT_DEBUG,
    LOG_FORMAT_INFO,
    set_logger_level,
    setup_logger,
)


class TestSetLoggerLevel(unittest.TestCase):
    def _make_logger(self, name):
        # setup_logger() only creates handlers on the first call for a given
        # name (logging.getLogger returns the same singleton afterwards), so
        # each test uses a unique name to avoid leaking handlers across tests.
        return setup_logger(name, f"/tmp/{name}.log")

    def test_raises_level_and_switches_to_debug_formatter(self):
        logger = self._make_logger("test_set_logger_level_to_debug")
        set_logger_level(logger, logging.DEBUG)

        self.assertEqual(logger.level, logging.DEBUG)
        for handler in logger.handlers:
            self.assertEqual(handler.formatter._fmt, LOG_FORMAT_DEBUG)

    def test_lowers_level_and_switches_back_to_info_formatter(self):
        logger = self._make_logger("test_set_logger_level_back_to_info")
        set_logger_level(logger, logging.DEBUG)
        set_logger_level(logger, logging.INFO)

        self.assertEqual(logger.level, logging.INFO)
        for handler in logger.handlers:
            self.assertEqual(handler.formatter._fmt, LOG_FORMAT_INFO)

    def test_updates_every_handler_not_just_the_first(self):
        logger = self._make_logger("test_set_logger_level_all_handlers")
        self.assertGreaterEqual(len(logger.handlers), 2)  # console + file, per setup_logger()

        set_logger_level(logger, logging.WARNING)

        for handler in logger.handlers:
            self.assertEqual(handler.formatter._fmt, LOG_FORMAT_INFO)  # WARNING != DEBUG
        self.assertEqual(logger.level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()
