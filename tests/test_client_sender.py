"""Comprehensive tests for client/sender.py TransactionSender class.

Tests cover happy path, error handling, message filtering, and retry logic.
Uses dependency injection (mock transport) and threading for simulating
async server responses.
"""
import unittest
import threading
import time
from unittest.mock import Mock, call, ANY, patch
from dataclasses import dataclass

from client.sender import SendResult, SendSession, TransactionSender, create_preview
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
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)
        self.assertEqual(sender.timeout_seconds, 30)
        self.assertEqual(sender.max_retries, 3)
        self.assertEqual(len(sender.sessions), 0)

    def test_init_with_custom_values(self):
        """Initialize with custom timeout and retries."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=60, max_retries=5)
        self.assertEqual(sender.timeout_seconds, 60)
        self.assertEqual(sender.max_retries, 5)

    def test_init_invalid_timeout(self):
        """Negative timeout raises ValueError."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        with self.assertRaises(ValueError):
            TransactionSender(transport, timeout_seconds=-1)

    def test_init_invalid_retries(self):
        """Negative retries raises ValueError."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        with self.assertRaises(ValueError):
            TransactionSender(transport, max_retries=-1)

    def test_init_registers_handler(self):
        """Initialization calls set_message_handler on transport."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)
        transport.set_message_handler.assert_called_once()


class TestTransactionSenderSingleChunk(unittest.TestCase):
    """Tests for single-chunk transaction sending (happy path)."""

    def test_single_chunk_success(self):
        """Send single-chunk transaction successfully."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        # Capture the handler callback
        handler = transport.set_message_handler.call_args[0][0]

        # Send transaction in background thread
        tx_hex = "deadbeef" * 20  # 160 hex chars = 1 chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        # Let sender send chunk
        time.sleep(0.2)

        # Verify chunk was sent
        self.assertEqual(transport.send.call_count, 1)
        sent_msg = transport.send.call_args[0][0]
        self.assertIn("BTC_TX|", sent_msg)
        self.assertIn("|1/1|", sent_msg)

        # Extract session ID from message
        parts = sent_msg.split("|")
        session_id = parts[1]

        # Simulate server ACK
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)

        # Simulate final ACK
        handler(f"BTC_ACK|{session_id}|TXID:mynewtxid123", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Verify result
        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertTrue(result.success)
        self.assertEqual(result.txid, "mynewtxid123")

    def test_invalid_hex_returns_error(self):
        """Invalid hex returns error in SendResult."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        result = sender.send_transaction("deadbeefZZZ", "!dest1234")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        # Error could be about invalid chars or odd length
        self.assertTrue("invalid" in result.error.lower() or "even" in result.error.lower())

    def test_empty_hex_returns_error(self):
        """Empty hex returns error in SendResult."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        result = sender.send_transaction("", "!dest1234")
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_send_transaction_validates_destination_via_transport(self):
        """Story 30.2: destination format is transport-specific, so
        send_transaction() delegates to the transport's own
        validate_destination() rather than a hardcoded rule."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        sender.send_transaction("deadbeef" * 20, "!dest1234")
        transport.validate_destination.assert_called_once_with("!dest1234")

    def test_send_transaction_uses_transport_max_chunk_size(self):
        """Issue 51: chunk size is transport-specific too - a size safe for
        one transport (e.g. Meshtastic's 170) can be rejected outright by
        another's stricter per-message cap (confirmed via real hardware
        against MeshCore), so send_transaction() must chunk using the
        transport's own max_chunk_size, not a hardcoded default."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        transport.max_chunk_size = 42
        sender = TransactionSender(transport)

        with patch("client.sender.create_session") as mock_create_session:
            mock_create_session.side_effect = ValueError("stop here")
            sender.send_transaction("deadbeef" * 20, "!dest1234")

        mock_create_session.assert_called_once_with(
            "deadbeef" * 20, chunk_size=42
        )

    def test_invalid_destination_returns_error_without_sending(self):
        """Issue 30: a malformed destination is rejected before ever
        touching transport.send(), same as invalid tx hex already was -
        now driven by whatever the transport's own validate_destination()
        raises, instead of a hardcoded Meshtastic-shaped rule."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        transport.validate_destination.side_effect = ValueError(
            "Destination cannot be empty"
        )
        sender = TransactionSender(transport)

        result = sender.send_transaction("deadbeef" * 20, "")
        self.assertFalse(result.success)
        self.assertIn("Destination", result.error)
        transport.send.assert_not_called()


class TestTransactionSenderMultiChunk(unittest.TestCase):
    """Tests for multi-chunk transaction sending."""

    def test_three_chunks_success(self):
        """Send three-chunk transaction successfully."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=5)

        handler = transport.set_message_handler.call_args[0][0]

        # Create 3-chunk transaction (needs > 510 hex chars)
        tx_hex = "abcd" * 150  # 600 hex chars = 4 chunks (170/170/170/90)
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        # Get session ID from first message
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Acknowledge each chunk (with proper format)
        for chunk_num in range(1, 5):  # 4 chunks
            if chunk_num < 4:
                # For non-final chunks, use REQUEST_CHUNK format
                handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|REQUEST_CHUNK|{chunk_num + 1}", "!server")
            else:
                # For final chunk, use ALL_CHUNKS_RECEIVED
                handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|ALL_CHUNKS_RECEIVED", "!server")
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
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=3)

        handler = transport.set_message_handler.call_args[0][0]

        # Use single-chunk transaction (small hex)
        tx_hex = "beef" * 20  # 80 hex chars = 1 chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        # Get session ID
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Let first attempt timeout (1 second)
        time.sleep(1.2)

        # On retry, send ACK
        time.sleep(0.2)
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:retried", "!server")
        time.sleep(0.1)

        thread.join(timeout=15)

        # Should have sent twice (initial + 1 retry)
        self.assertGreaterEqual(transport.send.call_count, 2)

        # Should succeed after retry
        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertTrue(result.success, f"Expected success but got: {result.error}")

    def test_max_retries_exhausted(self):
        """Chunk times out after max retries, returns error."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
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

    def test_send_exception_retries_then_succeeds(self):
        """A raised exception from transport.send() (e.g. a clean
        TransportSendError) retries instead of failing immediately
        (Issue 62) - same retry budget as an ACK timeout."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=3)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 20  # 1 chunk
        result_holder = []
        session_id_holder = []
        call_count = {"n": 0}

        def send_side_effect(msg, dest):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("no_event_received")
            session_id_holder.append(msg.split("|")[1])

        transport.send.side_effect = send_side_effect

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        # The exception path retries immediately (no timeout wait), so a
        # short sleep is enough to observe the second attempt.
        time.sleep(0.3)
        self.assertEqual(transport.send.call_count, 2, "expected an immediate retry after the exception")

        session_id = session_id_holder[0]
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:retried", "!server")

        thread.join(timeout=10)

        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertTrue(result.success, f"Expected success but got: {result.error}")

    def test_send_exception_exhausts_retries_then_fails(self):
        """A transport.send() that always raises exhausts the retry
        budget (same as timeouts do) rather than failing on the first
        attempt (Issue 62)."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=1)
        transport.send.side_effect = RuntimeError("no_event_received")

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()
        thread.join(timeout=10)

        # Initial attempt + 1 retry = 2 calls before giving up.
        self.assertEqual(transport.send.call_count, 2)

        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("no_event_received", result.error)

    def test_final_ack_retry_resends_last_chunk_then_succeeds(self):
        """A lost final BTC_ACK now gets retried by resending the last
        chunk (Issue 64), instead of failing on the first missed reply -
        mirrors the server's real behavior of resending its cached final
        reply when it sees the last chunk again."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=0.2, max_retries=3)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 20  # 1 chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        time.sleep(0.1)
        first_msg = transport.send.call_args_list[0][0][0]
        session_id = first_msg.split("|")[1]

        # ACK the chunk, but never send the final BTC_ACK yet - let the
        # final-ack wait (timeout_seconds * 2 = 0.4s) time out once.
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")

        # Wait past the first final-ack timeout so the last chunk gets
        # resent, then reply with the final ACK.
        time.sleep(0.5)
        self.assertEqual(transport.send.call_count, 2, "expected the last chunk to be resent after the final-ack timeout")
        handler(f"BTC_ACK|{session_id}|TXID:retried_final", "!server")

        thread.join(timeout=10)

        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertTrue(result.success, f"Expected success but got: {result.error}")
        self.assertEqual(result.txid, "retried_final")

    def test_final_ack_exhausts_retries_then_fails(self):
        """A final BTC_ACK that never arrives, even after resends,
        eventually fails with the same message as before (Issue 64) -
        exhausts the same max_retries budget as chunk sends."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=0.1, max_retries=1)

        # Don't send any final ACK - let everything time out.
        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 20  # 1 chunk
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=True)
        thread.start()

        # Short margin below timeout_seconds (0.1s) so the chunk-ack wait
        # itself never times out and retries before this ACK arrives.
        time.sleep(0.02)
        first_msg = transport.send.call_args_list[0][0][0]
        session_id = first_msg.split("|")[1]
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")

        thread.join(timeout=10)

        # Initial chunk send + 1 final-ack-triggered resend (max_retries=1).
        self.assertEqual(transport.send.call_count, 2)

        self.assertEqual(len(result_holder), 1)
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No final ACK from relay")


class TestTransactionSenderErrorHandling(unittest.TestCase):
    """Tests for error handling (NACK, server errors)."""

    def test_nack_message_fails_transaction(self):
        """Receiving NACK fails the transaction."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "dead" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        # Get session ID
        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # Send NACK instead of ACK
        handler(f"BTC_NACK|{session_id}|Invalid transaction format", "!server")
        time.sleep(0.1)

        thread.join(timeout=5)

        # Should fail
        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("Invalid transaction format", result.error)

    def test_nack_on_final_ack(self):
        """NACK received after all chunks sent."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "beef" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

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

        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertIn("insufficient funds", result.error)

    def test_nack_arriving_during_a_retry_wait_is_handled_correctly(self):
        """Regression/confirmation test for Issue 40's follow-up question:
        does the client correctly handle a NACK it wasn't specifically
        expecting at that point (e.g. a server-side reassembly-timeout
        NACK) if it arrives while a chunk is already on a *retry*
        attempt, not just during the very first wait?

        _handle_nack() signals every chunk's response event, regardless
        of which one is currently in flight - so this should unblock the
        retry's event.wait() immediately and propagate the NACK's real
        reason, the same as it does for the first-attempt case already
        covered by test_nack_message_fails_transaction(). This test
        forces an actual retry first (no ACK on attempt 1) before
        sending the NACK on attempt 2, to prove that specifically."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=0.2, max_retries=3)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "dead" * 50  # 1 chunk
        result_holder = []

        def send_in_thread():
            result_holder.append(sender.send_transaction(tx_hex, "!dest1234"))

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        # Let the first attempt time out on its own (no ACK) - forces a
        # real retry, so the NACK below arrives during attempt 2, not
        # attempt 1.
        time.sleep(0.3)
        self.assertEqual(transport.send.call_count, 2, "expected a retry to have happened by now")

        first_msg = transport.send.call_args_list[0][0][0]
        session_id = first_msg.split("|")[1]

        handler(f"BTC_NACK|{session_id}|Reassembly timeout", "!server")

        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Reassembly timeout")


class TestTransactionSenderMessageFiltering(unittest.TestCase):
    """Tests for message filtering (wrong session, malformed)."""

    def test_ignore_wrong_session(self):
        """Ignore ACK for different session ID."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=1)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        # Send ACK for wrong session ID
        handler(f"BTC_CHUNK_ACK|wrongsession|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)

        # Should timeout eventually
        thread.join(timeout=10)

        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertFalse(result.success)

    def test_ignore_malformed_message(self):
        """Ignore completely malformed messages."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=1, max_retries=1)

        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "cafe" * 50
        result_holder = []

        def send_in_thread():
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        # Send garbage
        handler("GARBAGE|DATA|HERE", "!server")
        time.sleep(0.1)

        # Should timeout, not crash
        thread.join(timeout=10)

        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertFalse(result.success)


class TestTransactionSenderProgressCallback(unittest.TestCase):
    """Tests for optional on_progress callback."""

    def test_progress_callback_called(self):
        """Progress callback is called for each chunk ACK."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
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

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        # ACK all chunks (with proper format)
        for chunk_num in range(1, 5):
            if chunk_num < 4:
                handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|REQUEST_CHUNK|{chunk_num + 1}", "!server")
            else:
                handler(f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|ALL_CHUNKS_RECEIVED", "!server")
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
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=2)

        handler = transport.set_message_handler.call_args[0][0]

        # Single-chunk transaction
        tx_hex = "dead" * 20  # 80 hex chars = 1 chunk
        result_holder = []

        def send_in_thread():
            # No on_progress callback
            result = sender.send_transaction(tx_hex, "!dest1234")
            result_holder.append(result)

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()

        time.sleep(0.2)

        first_msg = transport.send.call_args_list[0][0][0]
        parts = first_msg.split("|")
        session_id = parts[1]

        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:noprogress", "!server")
        time.sleep(0.1)

        thread.join(timeout=10)

        self.assertGreater(len(result_holder), 0)
        result = result_holder[0]
        self.assertTrue(result.success)


class TestTransactionSenderAbort(unittest.TestCase):
    """TransactionSender is designed for one send in flight per instance
    (see the class docstring) - abort() and its underlying event are
    instance-wide, not per-session. CLI and GUI both already create a
    fresh TransactionSender per send and never call send_transaction()
    concurrently on one instance."""

    def test_abort_stops_an_in_progress_send(self):
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=5)
        handler = transport.set_message_handler.call_args[0][0]

        tx_hex = "deadbeef" * 20  # 1 chunk
        result_holder = []

        def send_in_thread():
            result_holder.append(sender.send_transaction(tx_hex, "!dest1234"))

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()
        time.sleep(0.2)

        sender.abort()

        sent_msg = transport.send.call_args[0][0]
        session_id = sent_msg.split("|")[1]
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        thread.join(timeout=5)

        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Aborted by user")

    def test_abort_stops_a_chunk_stuck_retrying_on_timeout(self):
        """Regression test for Issue 38: previously, _abort_event was only
        checked in the ACK-received branch of _send_all_chunks() - pressing
        Abort while a chunk was stuck waiting for/retrying an ACK that
        never arrives had no effect until the retry budget ran out on its
        own (up to max_retries full timeout_seconds cycles later). Given
        no ACK is ever delivered and abort() is called during the first
        wait, Then the send stops with "Aborted by user" after (at most)
        one timeout cycle, not after exhausting all retries."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=0.2, max_retries=3)

        tx_hex = "deadbeef" * 20  # 1 chunk
        result_holder = []

        def send_in_thread():
            result_holder.append(sender.send_transaction(tx_hex, "!dest1234"))

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()
        time.sleep(0.05)  # still inside the first ACK wait

        sender.abort()

        # No handler ever fires an ACK - if the fix didn't work, this would
        # take ~4 timeout cycles (0.8s+) and fail with a timeout error
        # instead of stopping after roughly one cycle.
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

        result = result_holder[0]
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Aborted by user")

    def test_abort_before_any_send_does_not_raise(self):
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport)
        sender.abort()  # Should not raise even with nothing in flight

    def test_abort_event_is_cleared_at_the_start_of_each_send(self):
        """A prior send's abort state must not leak into the next send on
        the same instance - each send_transaction() call starts clean."""
        transport = Mock(spec=BaseTransport, max_chunk_size=170)
        sender = TransactionSender(transport, timeout_seconds=5)
        handler = transport.set_message_handler.call_args[0][0]

        # First send: abort it.
        result1 = sender.send_transaction("deadbeefZZ", "!dest1")  # invalid hex, fails fast
        self.assertFalse(result1.success)
        sender.abort()

        # Second send on the same instance must not start pre-aborted.
        tx_hex = "cafebabe" * 20  # 1 chunk
        result_holder = []

        def send_in_thread():
            result_holder.append(sender.send_transaction(tx_hex, "!dest2"))

        thread = threading.Thread(target=send_in_thread, daemon=False)
        thread.start()
        time.sleep(0.2)

        sent_msg = transport.send.call_args[0][0]
        session_id = sent_msg.split("|")[1]
        handler(f"BTC_CHUNK_ACK|{session_id}|1|ALL_CHUNKS_RECEIVED", "!server")
        time.sleep(0.1)
        handler(f"BTC_ACK|{session_id}|TXID:secondsendtxid", "!server")
        thread.join(timeout=5)

        result = result_holder[0]
        self.assertTrue(result.success)
        self.assertEqual(result.txid, "secondsendtxid")


class TestCreatePreviewChunkSize(unittest.TestCase):
    """Issue 51: create_preview() takes an optional chunk_size so a caller
    previewing for a specific transport (e.g. the CLI's --dry-run) sees
    accurate chunk counts, not just Meshtastic's default."""

    def test_default_chunk_size_matches_meshtastic(self):
        from core.constants import DEFAULT_CHUNK_SIZE

        preview = create_preview("ab" * 100)  # 200 hex chars
        expected_chunks = -(-200 // DEFAULT_CHUNK_SIZE)  # ceil division
        self.assertEqual(preview.total_chunks, expected_chunks)

    def test_custom_chunk_size_changes_total_chunks(self):
        preview = create_preview("ab" * 100, chunk_size=50)  # 200 hex chars
        self.assertEqual(preview.total_chunks, 4)


if __name__ == "__main__":
    unittest.main()
