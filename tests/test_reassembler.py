"""Tests for core/reassembler.py's TransactionReassembler class.

Relocated from tests/test_btcmesh_server.py (Story 23.3) - these tests
exercise TransactionReassembler directly and have no dependency on
btcmesh_server.py, they were just historically written before the
reassembler was extracted into its own core/ module.
"""
import unittest
from unittest.mock import MagicMock, patch

from core.reassembler import TransactionReassembler


class TestTransactionReassemblerStory21(unittest.TestCase):
    def setUp(self):
        # Patch logger for log assertions
        self.logger_patcher = patch("core.reassembler.server_logger", MagicMock())
        self.mock_logger = self.logger_patcher.start()
        self.reassembler = TransactionReassembler(
            timeout_seconds=1
        )  # Short timeout for test
        # Use already-formatted sender ID (server layer handles formatting)
        self.sender_id = "!3039"  # Equivalent to formatting 12345 as !hex
        self.session_id = "story21sess"

    def tearDown(self):
        self.logger_patcher.stop()

    def test_logs_on_new_session_and_chunk(self):
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        self.reassembler.add_chunk(self.sender_id, chunk1)
        # Should log new session start and chunk add
        log_ctx = f"[Sender: {self.sender_id}, Session: {self.session_id}]"
        self.mock_logger.info.assert_any_call(
            f"{log_ctx} New reassembly session started. Expecting 2 chunks."
        )
        self.mock_logger.debug.assert_any_call(
            f"{log_ctx} Added chunk 1/2. Collected 1 chunks."
        )

    def test_logs_on_duplicate_chunk(self):
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        self.reassembler.add_chunk(self.sender_id, chunk1)
        self.reassembler.add_chunk(self.sender_id, chunk1)  # Duplicate
        log_ctx = f"[Sender: {self.sender_id}, Session: {self.session_id}]"
        self.mock_logger.warning.assert_any_call(
            f"{log_ctx} Duplicate chunk 1/2 received. Ignoring."
        )

    def test_logs_on_out_of_order_and_reassembly_success(self):
        chunk2 = f"BTC_TX|{self.session_id}|2/2|BBB"
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        self.reassembler.add_chunk(self.sender_id, chunk2)
        self.reassembler.add_chunk(self.sender_id, chunk1)
        log_ctx = f"[Sender: {self.sender_id}, Session: {self.session_id}]"
        self.mock_logger.debug.assert_any_call(
            f"{log_ctx} Added chunk 2/2. Collected 1 chunks."
        )
        self.mock_logger.debug.assert_any_call(
            f"{log_ctx} Added chunk 1/2. Collected 2 chunks."
        )
        self.mock_logger.info.assert_any_call(
            f"{log_ctx} All 2 chunks received. Attempting reassembly."
        )
        self.mock_logger.info.assert_any_call(f"{log_ctx} Reassembly successful.")

    def test_logs_on_timeout(self):
        chunk1 = f"BTC_TX|{self.session_id}|1/2|AAA"
        self.reassembler.add_chunk(self.sender_id, chunk1)
        import time as _time

        _time.sleep(1.1)
        self.reassembler.cleanup_stale_sessions()
        # Timeout log uses the sender_id as provided (already formatted)
        log_ctx = f"[Sender: {self.sender_id}, Session: {self.session_id}]"
        self.mock_logger.warning.assert_any_call(
            f"{log_ctx} Reassembly timeout after 1s. Received 1/2 chunks. Discarding."
        )
        self.mock_logger.info.assert_any_call(
            "Identified 1 stale reassembly sessions for cleanup and NACK."
        )

    def test_logs_timeout_value_on_init(self):
        # The info log for timeout value should be called on init
        self.mock_logger.info.assert_any_call(
            "TransactionReassembler initialized with timeout: 1s"
        )


class TestHexValidationStory22(unittest.TestCase):
    def setUp(self):
        from core.reassembler import TransactionReassembler

        self.reassembler = TransactionReassembler(timeout_seconds=1)
        self.sender_id = 54321
        self.session_id = "hexval22"

    def test_valid_hex_string(self):
        """Given a valid hex string, When validated, Then it passes validation."""
        valid_hex = "deadbeefCAFEBABE0123456789abcdef"
        # Should not raise
        try:
            int(valid_hex, 16)
        except ValueError:
            self.fail("Valid hex string did not pass validation")

    def test_invalid_hex_string(self):
        """Given an invalid hex string, When validated, Then it fails validation and logs error."""
        invalid_hex = "deadbeefZZZ01234"
        with self.assertRaises(ValueError):
            int(invalid_hex, 16)

    def test_integration_reassembled_hex_validation(self):
        """Given a reassembled payload, When it is not valid hex, Then the server should log and prepare NACK."""
        # Simulate reassembly
        chunk1 = f"BTC_TX|{self.session_id}|1/2|deadbeef"
        chunk2 = f"BTC_TX|{self.session_id}|2/2|ZZZ01234"  # Invalid hex part
        self.reassembler.add_chunk(self.sender_id, chunk1)
        reassembled = self.reassembler.add_chunk(self.sender_id, chunk2)
        self.assertEqual(reassembled, "deadbeefZZZ01234")
        # Now validate
        with self.assertRaises(ValueError):
            int(reassembled, 16)

        # In the real server, this would trigger a NACK and log an error


if __name__ == "__main__":
    unittest.main()
