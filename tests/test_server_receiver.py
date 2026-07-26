"""Tests for server/receiver.py TransactionReceiver class.

Tests cover happy path (single/multi-chunk), broadcast success/failure,
concise error mapping, malformed chunks, timeout handling, and message
filtering. Uses dependency injection (mock transport + mock RPC client).
"""
import unittest
from unittest.mock import Mock

from server.receiver import (
    BroadcastResult,
    ChunkReceived,
    TransactionReceiver,
    _concise_error_message,
)
from transport.base import BaseTransport
from core.rpc_client import BitcoinRPCClient
from core.reassembler import TransactionReassembler


def make_receiver(**kwargs):
    """Helper: build a TransactionReceiver with mock transport/rpc_client,
    returning (receiver, transport_mock, rpc_client_mock, handler)."""
    transport = Mock(spec=BaseTransport)
    rpc_client = Mock(spec=BitcoinRPCClient)
    receiver = TransactionReceiver(transport, rpc_client, **kwargs)
    handler = transport.set_message_handler.call_args[0][0]
    return receiver, transport, rpc_client, handler


class TestTransactionReceiverConstruction(unittest.TestCase):
    """Tests for __init__ / message handler registration."""

    def test_registers_message_handler_on_construction(self):
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        TransactionReceiver(transport, rpc_client)
        transport.set_message_handler.assert_called_once()

    def test_uses_default_reassembler_when_none_provided(self):
        receiver, _, _, _ = make_receiver()
        self.assertIsInstance(receiver.reassembler, TransactionReassembler)

    def test_uses_injected_reassembler(self):
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = TransactionReassembler()
        receiver = TransactionReceiver(transport, rpc_client, reassembler=reassembler)
        self.assertIs(receiver.reassembler, reassembler)

    def test_works_with_no_callbacks_provided(self):
        """All callbacks are optional."""
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = ("txid123", None)
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")
        # Should not raise despite no callbacks registered


class TestTransactionReceiverChunkHandling(unittest.TestCase):
    """Tests for single/multi-chunk reception and ACKing."""

    def test_ignores_non_chunk_messages(self):
        receiver, transport, rpc_client, handler = make_receiver()
        handler("Hello world", "!sender1")
        # transport.send() is the only channel for both ACK and NACK replies,
        # so asserting it was never called proves neither was sent - a
        # non-BTC_TX message gets silently ignored, not NACKed.
        transport.send.assert_not_called()
        rpc_client.broadcast_transaction.assert_not_called()
        # Proves it was never handed to the reassembler at all (not just
        # that no ACK/NACK/broadcast happened) - non-chunk messages return
        # before add_chunk() is ever called, so no session gets created.
        self.assertEqual(receiver.get_active_sessions(), [])

    def test_single_chunk_acks_all_chunks_received(self):
        on_chunk_received = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_chunk_received=on_chunk_received
        )
        rpc_client.broadcast_transaction.return_value = ("mytxid", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        # ACK for the single chunk
        ack_call = transport.send.call_args_list[0]
        self.assertEqual(ack_call.args[0], "BTC_CHUNK_ACK|sess1|1|ALL_CHUNKS_RECEIVED")
        self.assertEqual(ack_call.args[1], "!sender1")

        on_chunk_received.assert_called_once_with(
            ChunkReceived(session_id="sess1", sender_id="!sender1", chunk_num=1, total_chunks=1)
        )

    def test_multi_chunk_requests_next_chunk(self):
        receiver, transport, rpc_client, handler = make_receiver()

        handler("BTC_TX|sess2|1/3|aabb", "!sender1")

        ack_call = transport.send.call_args_list[0]
        self.assertEqual(ack_call.args[0], "BTC_CHUNK_ACK|sess2|1|REQUEST_CHUNK|2")
        self.assertEqual(ack_call.args[1], "!sender1")
        rpc_client.broadcast_transaction.assert_not_called()

    def test_multi_chunk_full_sequence_reassembles(self):
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = ("finaltxid", None)

        handler("BTC_TX|sess3|1/2|dead", "!sender1")
        handler("BTC_TX|sess3|2/2|beef", "!sender1")

        rpc_client.broadcast_transaction.assert_called_once_with("deadbeef")


class TestTransactionReceiverBroadcast(unittest.TestCase):
    """Tests for RPC broadcast success/failure handling."""

    def test_broadcast_success_sends_ack_and_fires_callback(self):
        on_broadcast = Mock()
        receiver, transport, rpc_client, handler = make_receiver(on_broadcast=on_broadcast)
        rpc_client.broadcast_transaction.return_value = ("txid789", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        final_ack_call = transport.send.call_args_list[-1]
        self.assertEqual(final_ack_call.args[0], "BTC_ACK|sess1|TXID:txid789")
        self.assertEqual(final_ack_call.args[1], "!sender1")

        on_broadcast.assert_called_once_with(
            BroadcastResult(
                session_id="sess1", sender_id="!sender1", success=True,
                txid="txid789", raw_tx="deadbeef",
            )
        )

    def test_broadcast_failure_sends_nack_and_fires_callback(self):
        on_broadcast = Mock()
        receiver, transport, rpc_client, handler = make_receiver(on_broadcast=on_broadcast)
        rpc_client.broadcast_transaction.return_value = (None, "insufficient fee for this tx")

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        final_nack_call = transport.send.call_args_list[-1]
        self.assertEqual(final_nack_call.args[0], "BTC_NACK|sess1|Insufficient fee")
        self.assertEqual(final_nack_call.args[1], "!sender1")

        on_broadcast.assert_called_once_with(
            BroadcastResult(
                session_id="sess1", sender_id="!sender1", success=False,
                error="insufficient fee for this tx", raw_tx="deadbeef",
            )
        )


class TestConciseErrorMessage(unittest.TestCase):
    """Tests for _concise_error_message()'s mapping table."""

    def test_maps_known_error_substrings(self):
        cases = [
            ("Transaction outputs already in utxo set", "TX already in UTXO set"),
            ("Transaction already in block chain", "TX already in chain"),
            ("insufficient fee", "Insufficient fee"),
            ("missing inputs", "Missing inputs"),
            ("bad-txns-inputs-spent", "Inputs spent"),
            ("bad-txns-in-belowout", "Input < Output"),
            ("too-long-mempool-chain", "Chain too long"),
            ("mempool full", "Mempool full"),
            ("replacement transaction rejected", "RBF disabled"),
            ("non-mandatory-script-verify-flag failed", "Script verify failed"),
            ("transaction already abandoned", "TX abandoned"),
            ("bad-txns-nonstandard-inputs", "Non-std inputs"),
            ("bad-txns-oversize", "TX too large"),
            ("dust", "Dust output"),
            ("fee is too high", "Fee too high"),
            ("absurdly-high-fee", "Absurd fee"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(_concise_error_message(raw), expected)

    def test_maps_version_reject_combo(self):
        self.assertEqual(
            _concise_error_message("Version 2 transaction rejected by policy"),
            "Version rejected",
        )

    def test_unmapped_error_passed_through_unchanged(self):
        self.assertEqual(
            _concise_error_message("some totally unmapped error"),
            "some totally unmapped error",
        )


class TestTransactionReceiverErrorHandling(unittest.TestCase):
    """Tests for malformed chunks and unexpected errors."""

    def test_mismatched_total_chunks_sends_nack_and_discards_session(self):
        """A session is created by the first chunk, then discarded by the
        reassembler's own error handling when a later chunk reports a
        different total_chunks - distinct from the "never added at all"
        case below."""
        on_error = Mock()
        receiver, transport, rpc_client, handler = make_receiver(on_error=on_error)

        handler("BTC_TX|sessX|1/2|dead", "!sender1")
        self.assertEqual(len(receiver.get_active_sessions()), 1)

        handler("BTC_TX|sessX|1/3|dead", "!sender1")

        nack_call = transport.send.call_args_list[-1]
        self.assertTrue(nack_call.args[0].startswith("BTC_NACK|sessX|"))
        self.assertEqual(nack_call.args[1], "!sender1")
        on_error.assert_called_once()
        self.assertEqual(on_error.call_args.args[0], "sessX")
        self.assertEqual(on_error.call_args.args[1], "!sender1")
        # The reassembler discards the mismatched session as part of raising
        # MismatchedTotalChunksError - no session lingers afterward.
        self.assertEqual(receiver.get_active_sessions(), [])

    def test_invalid_chunk_format_never_added_to_reassembler(self):
        """A chunk that doesn't parse at all (non-numeric chunk/total) is
        rejected by the reassembler's own _parse_chunk() before any session
        dict is touched - proving it was never added, not added-then-removed."""
        on_error = Mock()
        receiver, transport, rpc_client, handler = make_receiver(on_error=on_error)

        handler("BTC_TX|sessBad|notanumber/2|deadbeef", "!sender1")

        nack_call = transport.send.call_args_list[-1]
        self.assertTrue(nack_call.args[0].startswith("BTC_NACK|sessBad|"))
        self.assertIn("Invalid", nack_call.args[0])
        on_error.assert_called_once()
        # No session was ever created for this sender/session_id.
        self.assertEqual(receiver.get_active_sessions(), [])

    def test_nack_message_truncated_when_too_long(self):
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = (None, "x" * 500)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        nack_call = transport.send.call_args_list[-1]
        self.assertLessEqual(len(nack_call.args[0]), 200)
        self.assertTrue(nack_call.args[0].endswith("..."))


class TestTransactionReceiverTimeouts(unittest.TestCase):
    """Tests for check_timeouts()."""

    def test_no_stale_sessions_is_noop(self):
        receiver, transport, rpc_client, handler = make_receiver()
        receiver.check_timeouts()
        transport.send.assert_not_called()

    def test_stale_session_sends_nack_and_fires_on_error(self):
        on_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.cleanup_stale_sessions.return_value = [
            {
                "sender_id_str": "!sender1",
                "tx_session_id": "sessTimeout",
                "error_message": "Timed out waiting for chunks",
            }
        ]
        receiver = TransactionReceiver(
            transport, rpc_client, reassembler=reassembler, on_error=on_error
        )

        receiver.check_timeouts()

        nack_call = transport.send.call_args_list[-1]
        self.assertEqual(
            nack_call.args[0], "BTC_NACK|sessTimeout|Timed out waiting for chunks"
        )
        self.assertEqual(nack_call.args[1], "!sender1")
        on_error.assert_called_once_with(
            "sessTimeout", "!sender1", "Timed out waiting for chunks"
        )


class TestTransactionReceiverActiveSessions(unittest.TestCase):
    """Tests for get_active_sessions()."""

    def test_delegates_to_reassembler(self):
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.get_active_sessions_info.return_value = [{"session_id": "abc"}]
        receiver = TransactionReceiver(transport, rpc_client, reassembler=reassembler)

        result = receiver.get_active_sessions()

        self.assertEqual(result, [{"session_id": "abc"}])
        reassembler.get_active_sessions_info.assert_called_once()


if __name__ == "__main__":
    unittest.main()
