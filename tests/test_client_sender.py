"""Comprehensive tests for client/sender.py TransactionSender class.

Tests cover happy path, error handling, message filtering, and retry logic.
Uses dependency injection (mock transport) and threading for simulating
async server responses.
"""
import unittest
import threading
import time
from unittest.mock import Mock, call, ANY
from dataclasses import dataclass

from client.sender import SendResult, SendSession, TransactionSender
from transport.base import BaseTransport
from core.message_types import ChunkAckMessage, AckMessage, NackMessage


class TestSendResult(unittest.TestCase):
    """Tests for SendResult dataclass validation."""

    def test_success_with_txid(self):
        """Success result must have txid."""
        result = SendResult(
            success=True,
            session_id="abc123",
            txid="txabc123def456",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.txid, "txabc123def456")
        self.assertIsNone(result.error)

    def test_success_without_txid_raises(self):
        """Success=True without txid raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            SendResult(
                success=True,
                session_id="abc123",
                txid=None,
            )
        self.assertIn("success=True requires txid", str(cm.exception))

    def test_failure_with_error(self):
        """Failure result must have error message."""
        result = SendResult(
            success=False,
            session_id="abc123",
            error="Timeout after 3 retries",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Timeout after 3 retries")
        self.assertIsNone(result.txid)

    def test_failure_without_error_raises(self):
        """Success=False without error raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            SendResult(
                success=False,
                session_id="abc123",
                error=None,
            )
        self.assertIn("success=False requires error", str(cm.exception))


class TestSendSession(unittest.TestCase):
    """Tests for SendSession internal state tracker."""

    def test_init(self):
        """SendSession initializes correctly."""
        session = SendSession("abc123", 3)
        self.assertEqual(session.session_id, "abc123")
        self.assertEqual(session.total_chunks, 3)
        self.assertEqual(len(session.chunks_sent), 0)
        self.assertEqual(len(session.chunks_acked), 0)
        self.assertFalse(session.failed)
        self.assertIsNone(session.error)

    def test_mark_chunk_sent(self):
        """Mark chunk as sent."""
        session = SendSession("abc123", 3)
        session.mark_chunk_sent(1)
        self.assertIn(1, session.chunks_sent)
        self.assertIn(1, session.sent_timestamps)

    def test_mark_chunk_acked(self):
        """Mark chunk as ACKed."""
        session = SendSession("abc123", 3)
        session.mark_chunk_acked(1)
        self.assertIn(1, session.chunks_acked)

    def test_is_complete(self):
        """Check completion state."""
        session = SendSession("abc123", 2)
        self.assertFalse(session.is_complete())
        session.mark_chunk_acked(1)
        self.assertFalse(session.is_complete())
        session.mark_chunk_acked(2)
        self.assertTrue(session.is_complete())

    def test_needs_resend(self):
        """Check if chunk needs resending (timeout)."""
        session = SendSession("abc123", 3)
        session.mark_chunk_sent(1)
        # Immediate check should be False
        self.assertFalse(session.needs_resend(1, 1.0))
        # After timeout should be True
        time.sleep(1.1)
        self.assertTrue(session.needs_resend(1, 1.0))

    def test_increment_retry(self):
        """Track retry attempts."""
        session = SendSession("abc123", 3)
        self.assertEqual(session.retry_counts.get(1, 0), 0)
        session.increment_retry(1)
        self.assertEqual(session.retry_counts.get(1, 0), 1)
        session.increment_retry(1)
        self.assertEqual(session.retry_counts.get(1, 0), 2)

    def test_threading_events(self):
        """Test threading event helpers."""
        session = SendSession("abc123", 3)
        event = session.get_response_event(1)
        self.assertIsNotNone(event)
        self.assertFalse(event.is_set())
        session.mark_chunk_acked(1)
        self.assertTrue(event.is_set())


class TestTransactionSenderInit(unittest.TestCase):
    """Tests for TransactionSender initialization."""

    def test_init_with_defaults(self):
        """Initialize with default timeout and retries."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)
        self.assertEqual(sender.timeout_seconds, 30)
        self.assertEqual(sender.max_retries, 3)
        self.assertEqual(len(sender.sessions), 0)

    def test_init_with_custom_values(self):
        """Initialize with custom timeout and retries."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=60, max_retries=5)
        self.assertEqual(sender.timeout_seconds, 60)
        self.assertEqual(sender.max_retries, 5)

    def test_init_invalid_timeout(self):
        """Negative timeout raises ValueError."""
        transport = Mock(spec=BaseTransport)
        with self.assertRaises(ValueError):
            TransactionSender(transport, timeout_seconds=-1)

    def test_init_invalid_retries(self):
        """Negative retries raises ValueError."""
        transport = Mock(spec=BaseTransport)
        with self.assertRaises(ValueError):
            TransactionSender(transport, max_retries=-1)

    def test_init_registers_handler(self):
        """Initialization calls set_message_handler on transport."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)
        transport.set_message_handler.assert_called_once()


class TestTransactionSenderSingleChunk(unittest.TestCase):
    """Tests for single-chunk transaction sending (happy path)."""

    def test_single_chunk_success(self):
        """Send single-chunk transaction successfully."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        # Capture the handler callback
        handler = transport.set_message_handler.call_args[0][0]

        # Send transaction in background thread
        tx_hex = "deadbeef" * 20  # 160 hex chars = 1 chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        # Let sender send chunk
        time.sleep(0.1)

        # Verify chunk was sent
        self.assertEqual(transport.send.call_count, 1)
        sent_msg = transport.send.call_args[0][0]
        self.assertIn("BTC_TX|", sent_msg)
        self.assertIn("|1/1|", sent_msg)

        # Simulate server ACK
        handler("BTC_CHUNK_ACK|abc123|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)

        # Simulate final ACK
        handler("BTC_ACK|abc123|TXID:mynewtxid123", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Verify result
        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertTrue(result.success)
        self.assertEqual(result.txid, "mynewtxid123")

    def test_invalid_hex_returns_error(self):
        """Invalid hex returns error in SendResult."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        result = sender.send_transaction("deadbeefZZZ", "!dest1234")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIn("invalid", result.error.lower())

    def test_empty_hex_returns_error(self):
        """Empty hex returns error in SendResult."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        result = sender.send_transaction("", "!dest1234")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)


class TestTransactionSenderMultiChunk(unittest.TestCase):
    """Tests for multi-chunk transaction sending."""

    def test_three_chunks_success(self):
        """Send three-chunk transaction successfully."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=5)

        handler = transport.set_message_handler.call_args[0][0]

        # Create 3-chunk transaction (needs > 510 hex chars)
        tx_hex = "abcd" * 150  # 600 hex chars = 4 chunks (170/170/170/90)
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        # Get session ID from first message
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Acknowledge each chunk
        for chunk_num in range(1, 5):  # 4 chunks
            handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|", "!server")
            time.sleep(0.05)

        # Send final ACK
        handler(f"BTC_ACK|{session_id}|TXID:finished3chunks", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Verify all chunks were sent
        self.assertEqual(transport.send.call_count, 4)

        # Verify result
        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertTrue(result.success)
        self.assertEqual(result.txid, "finished3chunks")


class TestTransactionSenderRetry(unittest.TestCase):
    """Tests for retry logic on timeout."""

    def test_retry_then_success(self):
        """Chunk times out, retries, then succeeds."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=3)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 50  # One chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        # Get session ID
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Let first attempt timeout
        time.sleep(1.2)

        # On retry, send ACK
        time.sleep(0.1)
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:retried", "!server")
        time.sleep(0.1)

        thread.join(timeout=10)

        # Should have sent twice (initial + 1 retry)
        self.assertGreaterEqual(transport.send.call_count, 2)

        # Should succeed after retry
        result = result_holder[0]
        self.assertTrue(result.success)

    def test_max_retries_exhausted(self):
        """Chunk times out after max retries, returns error."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=0.1, max_retries=1)

        # Don't send ACKs - let everything timeout
        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        thread.join(timeout=10)

        # Should fail after retries exhausted
        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("timeout", result.error.lower())


class TestTransactionSenderErrorHandling(unittest.TestCase):
    """Tests for error handling (NACK, server errors)."""

    def test_nack_message_fails_transaction(self):
        """Receiving NACK fails the transaction."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "dead" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        # Get session ID
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Send NACK instead of ACK
        handler(f"BTC_NACK|{session_id}|Invalid transaction format", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Should fail
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("Invalid transaction format", result.error)

    def test_nack_on_final_ack(self):
        """NACK received after all chunks sent."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # ACK the chunk
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)

        # NACK the final ACK
        handler(f"BTC_NACK|{session_id}|Cannot broadcast: insufficient funds", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("insufficient funds", result.error)


class TestTransactionSenderMessageFiltering(unittest.TestCase):
    """Tests for message filtering (wrong session, malformed)."""

    def test_ignore_wrong_session(self):
        """Ignore ACK for different session ID."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=1)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        # Send ACK for wrong session ID
        handler(f"BTC_CHUNK_ACK|wrongsession|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)

        # Should timeout eventually
        thread.join(timeout=10)

        result = result_holder[0]
        self.assertFalse(result.success)

    def test_ignore_malformed_message(self):
        """Ignore completely malformed messages."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=1)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        # Send garbage
        handler("GARBAGE|DATA|HERE", "!server")
        time.sleep(0.1)

        # Should timeout, not crash
        thread.join(timeout=10)

        result = result_holder[0]
        self.assertFalse(result.success)


class TestTransactionSenderProgressCallback(unittest.TestCase):
    """Tests for optional on_progress callback."""

    def test_progress_callback_called(self):
        """Progress callback is called for each chunk ACK."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        # Multi-chunk transaction
        tx_hex = "beef" * 150  # 600 hex chars = 4 chunks
        progress_calls = []

        def on_progress(chunk_num, total_chunks):
            progress_calls.append((chunk_num, total_chunks))

        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(
                tx_hex,
                "!dest1234",
                on_progress=on_progress,
            )
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # ACK all chunks
        for chunk_num in range(1, 5):
            handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|", "!server")
            time.sleep(0.05)

        # Send final ACK
        handler(f"BTC_ACK|{session_id}|TXID:testprogress", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Should have progress for each chunk
        self.assertGreater(len(progress_calls), 0)
        # Each should have (chunk_num, 4)
        for chunk_num, total in progress_calls:
            self.assertEqual(total, 4)

    def test_progress_callback_optional(self):
        """Progress callback can be None."""
        transport = Mock(spec=BaseTransport)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "dead" * 50
        result_holder = []

        def send_in_thread():
            # No on_progress callback
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)

        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:noprogress", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        result = result_holder[0]
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
