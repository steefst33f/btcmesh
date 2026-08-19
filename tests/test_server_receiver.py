"""Tests for server/receiver.py TransactionReceiver class.

Tests cover happy path (single/multi-chunk), broadcast success/failure,
concise error mapping, malformed chunks, timeout handling, and message
filtering. Uses dependency injection (mock transport + mock RPC client).
"""
import unittest
from unittest.mock import Mock, patch

from server.receiver import (
    BroadcastResult,
    ChunkReceived,
    TransactionReceiver,
    _concise_error_message,
)
from transport.base import BaseTransport
from core.rpc_client import BitcoinRPCClient
from core.reassembler import ReassemblyError, TransactionReassembler


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


class TestTransactionReceiverTransportError(unittest.TestCase):
    """Tests for on_transport_error (Story 26.5) - fired from _send() when
    the transport-level send actually fails (device wedged/disconnected)."""

    def test_on_transport_error_fires_when_ack_send_fails(self):
        on_transport_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        send_error = RuntimeError("device wedged")
        # Ack-send fails; the generic handler's own NACK retry attempt
        # succeeds - isolates this test to exactly the one failure being
        # tested (a device that fails every send is covered separately).
        transport.send.side_effect = [send_error, None]
        receiver = TransactionReceiver(
            transport, rpc_client, on_transport_error=on_transport_error
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_transport_error.assert_called_once_with(send_error)

    def test_on_transport_error_fires_for_every_failed_send_attempt(self):
        """A genuinely wedged device fails every send, including the
        generic handler's own NACK retry attempt - on_transport_error
        fires once per failed attempt, not just the first."""
        on_transport_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        transport.send.side_effect = RuntimeError("device wedged")
        receiver = TransactionReceiver(
            transport, rpc_client, on_transport_error=on_transport_error
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        self.assertEqual(on_transport_error.call_count, 2)

    def test_on_chunk_received_does_not_fire_when_ack_send_fails(self):
        """Regression guard: on_transport_error must be purely additive -
        existing control flow (on_chunk_received only firing after a
        successful ack) must be unchanged."""
        on_chunk_received = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        transport.send.side_effect = RuntimeError("device wedged")
        receiver = TransactionReceiver(
            transport, rpc_client, on_chunk_received=on_chunk_received
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_chunk_received.assert_not_called()

    def test_send_failure_still_reaches_generic_error_handler(self):
        """The generic except Exception branch in _on_message() still
        catches the re-raised transport error (unchanged from today) - so
        on_error also fires, in addition to on_transport_error."""
        on_error = Mock()
        on_transport_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        transport.send.side_effect = [RuntimeError("device wedged"), None]
        receiver = TransactionReceiver(
            transport, rpc_client,
            on_error=on_error, on_transport_error=on_transport_error,
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_transport_error.assert_called_once()
        on_error.assert_called_once()


class TestTransactionReceiverTransportSuccess(unittest.TestCase):
    """Tests for on_transport_success (Story 28.3 review fix) - fired from
    _send() symmetric with on_transport_error, for *any* successful reply
    send (chunk-ack, NACK, or final ACK alike), not just a fully-received
    chunk. See project/plans/story_28_3.md for why this needed fixing."""

    def test_on_transport_success_fires_when_ack_send_succeeds(self):
        on_transport_success = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_transport_success=on_transport_success
        )
        rpc_client.broadcast_transaction.return_value = ("mytxid", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        # Two successful sends for a single-chunk transaction that
        # completes: the chunk-ack, then the final BTC_ACK reply - both are
        # genuine successful local sends, both count.
        self.assertEqual(on_transport_success.call_count, 2)

    def test_on_transport_success_fires_for_a_nack_send_too(self):
        """A malformed chunk never reaches on_chunk_received, but the NACK
        reply for it is still a genuine successful local send - proof the
        device is alive even though the higher-level outcome is a failure."""
        on_transport_success = Mock()
        on_chunk_received = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_transport_success=on_transport_success,
            on_chunk_received=on_chunk_received,
        )

        handler("BTC_TX|sessBad|notanumber/2|deadbeef", "!sender1")

        on_chunk_received.assert_not_called()
        on_transport_success.assert_called_once_with()

    def test_on_transport_success_does_not_fire_when_send_fails(self):
        on_transport_success = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        transport.send.side_effect = RuntimeError("device wedged")
        receiver = TransactionReceiver(
            transport, rpc_client, on_transport_success=on_transport_success
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_transport_success.assert_not_called()


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

    def test_broadcast_with_no_rpc_client_sends_nack_and_fires_callback(self):
        """Given rpc_client=None (server started without a working RPC
        connection, per the documented Meshtastic-keeps-running behavior),
        When a transaction fully reassembles, Then the client gets a clear
        NACK instead of the server crashing with AttributeError - real bug
        found via hardware testing during Story 23.3 (see Issue 18)."""
        on_broadcast = Mock()
        on_error = Mock()
        transport = Mock(spec=BaseTransport)
        receiver = TransactionReceiver(
            transport, None, on_broadcast=on_broadcast, on_error=on_error
        )
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        final_nack_call = transport.send.call_args_list[-1]
        self.assertEqual(final_nack_call.args[0], "BTC_NACK|sess1|Bitcoin RPC not connected")
        self.assertEqual(final_nack_call.args[1], "!sender1")
        on_broadcast.assert_called_once_with(
            BroadcastResult(
                session_id="sess1", sender_id="!sender1", success=False,
                error="Bitcoin RPC not connected", raw_tx="deadbeef",
            )
        )
        # Must not be silently swallowed as a generic error - confirms this
        # goes through the dedicated no-RPC path, not the crash-and-catch one.
        on_error.assert_not_called()

    def test_broadcast_started_fires_before_rpc_call(self):
        on_broadcast_started = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_broadcast_started=on_broadcast_started
        )
        rpc_client.broadcast_transaction.return_value = ("txid789", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_broadcast_started.assert_called_once_with("sess1", "!sender1")

    def test_broadcast_started_not_fired_when_reassembly_incomplete(self):
        on_broadcast_started = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_broadcast_started=on_broadcast_started
        )

        handler("BTC_TX|sess2|1/2|aabb", "!sender1")

        on_broadcast_started.assert_not_called()
        rpc_client.broadcast_transaction.assert_not_called()


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

    def test_generic_reassembly_error_sends_nack_and_fires_on_error(self):
        """A ReassemblyError that isn't InvalidChunkFormatError/
        MismatchedTotalChunksError (some other reassembly problem) sends a
        NACK carrying the exception's own message, and notifies via
        on_error. Uses a mocked reassembler since this is about the
        receiver's own dispatch logic, not real reassembler behavior (which
        never actually raises a bare ReassemblyError). Issue 18 (real-world
        AttributeError repro) - this generic branch used to swallow the
        error silently with no NACK; fixed to match the specific-error
        branches above."""
        on_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.add_chunk.side_effect = ReassemblyError("some other reassembly problem")
        receiver = TransactionReceiver(transport, rpc_client, reassembler=reassembler, on_error=on_error)
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/2|deadbeef", "!sender1")

        nack_call = transport.send.call_args_list[-1]
        self.assertEqual(nack_call.args[0], "BTC_NACK|sess1|some other reassembly problem")
        self.assertEqual(nack_call.args[1], "!sender1")
        on_error.assert_called_once_with("sess1", "!sender1", "some other reassembly problem")

    def test_unexpected_exception_sends_generic_nack_and_fires_on_error(self):
        """A completely unexpected (non-ReassemblyError) exception from
        add_chunk() sends a NACK with a generic, wire-safe message (not the
        raw exception text, which is unconstrained and could contain
        internal details), while on_error still gets the real message for
        server-side logs."""
        on_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.add_chunk.side_effect = RuntimeError("totally unexpected")
        receiver = TransactionReceiver(transport, rpc_client, reassembler=reassembler, on_error=on_error)
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/2|deadbeef", "!sender1")

        nack_call = transport.send.call_args_list[-1]
        self.assertEqual(nack_call.args[0], "BTC_NACK|sess1|Internal server error")
        self.assertEqual(nack_call.args[1], "!sender1")
        on_error.assert_called_once_with("sess1", "!sender1", "totally unexpected")

    def test_secondary_nack_failure_does_not_escape_the_generic_handler(self):
        """If sending the NACK itself fails (e.g. the transport is also
        broken), that second failure must not propagate out of the message
        handler - it would crash whatever's dispatching messages to it."""
        on_error = Mock()
        transport = Mock(spec=BaseTransport)
        transport.send.side_effect = RuntimeError("transport is also broken")
        rpc_client = Mock(spec=BitcoinRPCClient)
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.add_chunk.side_effect = RuntimeError("totally unexpected")
        receiver = TransactionReceiver(transport, rpc_client, reassembler=reassembler, on_error=on_error)
        handler = transport.set_message_handler.call_args[0][0]

        handler("BTC_TX|sess1|1/2|deadbeef", "!sender1")  # must not raise

        on_error.assert_called_once_with("sess1", "!sender1", "totally unexpected")

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

    def test_does_not_crash_when_nack_send_fails_and_cleans_up_remaining_sessions(self):
        """A wedged device failing the NACK send during cleanup must not
        crash check_timeouts() (Story 26.5) or block cleaning up other
        stale sessions - on_transport_error still fires, on_error still
        fires for every session regardless of send success."""
        on_error = Mock()
        on_transport_error = Mock()
        transport = Mock(spec=BaseTransport)
        rpc_client = Mock(spec=BitcoinRPCClient)
        transport.send.side_effect = RuntimeError("device wedged")
        reassembler = Mock(spec=TransactionReassembler)
        reassembler.cleanup_stale_sessions.return_value = [
            {
                "sender_id_str": "!sender1",
                "tx_session_id": "sessA",
                "error_message": "Timed out waiting for chunks",
            },
            {
                "sender_id_str": "!sender2",
                "tx_session_id": "sessB",
                "error_message": "Timed out waiting for chunks",
            },
        ]
        receiver = TransactionReceiver(
            transport, rpc_client, reassembler=reassembler,
            on_error=on_error, on_transport_error=on_transport_error,
        )

        receiver.check_timeouts()  # must not raise

        self.assertEqual(on_transport_error.call_count, 2)
        self.assertEqual(on_error.call_count, 2)


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


class TestTransactionReceiverWireCallbacks(unittest.TestCase):
    """Tests for on_wire_sent/on_wire_received - the raw wire-format text of
    every reply and incoming chunk, for callers that want to display the raw
    protocol traffic (e.g. a GUI activity log) alongside the semantic events."""

    def test_wire_received_fires_with_raw_chunk_text(self):
        on_wire_received = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_received=on_wire_received
        )
        rpc_client.broadcast_transaction.return_value = ("txid123", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        on_wire_received.assert_called_once_with("BTC_TX|sess1|1/1|deadbeef")

    def test_wire_received_not_fired_for_non_chunk_messages(self):
        on_wire_received = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_received=on_wire_received
        )

        handler("Hello world", "!sender1")

        on_wire_received.assert_not_called()

    def test_wire_sent_fires_with_raw_chunk_ack_text(self):
        on_wire_sent = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_sent=on_wire_sent
        )

        handler("BTC_TX|sess2|1/3|aabb", "!sender1")

        on_wire_sent.assert_called_once_with("BTC_CHUNK_ACK|sess2|1|REQUEST_CHUNK|2")

    def test_wire_sent_fires_with_raw_broadcast_ack_text(self):
        on_wire_sent = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_sent=on_wire_sent
        )
        rpc_client.broadcast_transaction.return_value = ("mytxid", None)

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        # Two sends happen for a single-chunk transaction: the CHUNK_ACK, then
        # the final broadcast-success BTC_ACK - both should be reported.
        self.assertEqual(on_wire_sent.call_count, 2)
        self.assertEqual(
            on_wire_sent.call_args_list[0].args[0],
            "BTC_CHUNK_ACK|sess1|1|ALL_CHUNKS_RECEIVED",
        )
        self.assertEqual(
            on_wire_sent.call_args_list[1].args[0], "BTC_ACK|sess1|TXID:mytxid"
        )

    def test_wire_sent_fires_with_raw_broadcast_nack_text(self):
        on_wire_sent = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_sent=on_wire_sent
        )
        rpc_client.broadcast_transaction.return_value = (None, "insufficient fee")

        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        self.assertEqual(
            on_wire_sent.call_args_list[-1].args[0], "BTC_NACK|sess1|Insufficient fee"
        )

    def test_wire_sent_fires_with_raw_error_nack_text(self):
        on_wire_sent = Mock()
        receiver, transport, rpc_client, handler = make_receiver(
            on_wire_sent=on_wire_sent
        )

        handler("BTC_TX|sessBad|notanumber/2|deadbeef", "!sender1")

        self.assertTrue(on_wire_sent.call_args_list[-1].args[0].startswith("BTC_NACK|sessBad|"))

    def test_wire_sent_fires_on_timeout_nack(self):
        on_wire_sent = Mock()
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
            transport, rpc_client, reassembler=reassembler, on_wire_sent=on_wire_sent
        )

        receiver.check_timeouts()

        on_wire_sent.assert_called_once_with(
            "BTC_NACK|sessTimeout|Timed out waiting for chunks"
        )


class TestTransactionReceiverCompletedSessionCache(unittest.TestCase):
    """Tests for Issue 17: if the client never got the final ACK/NACK for a
    just-completed session and retransmits the last chunk, the server must
    resend that same cached reply instead of treating it as chunk 1 of a
    brand-new (bogus) session."""

    def test_retransmitted_last_chunk_after_success_resends_cached_ack(self):
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = ("mytxid", None)
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.reset_mock()
        rpc_client.broadcast_transaction.reset_mock()
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")  # client retransmits, never saw the ACK

        transport.send.assert_called_once_with("BTC_ACK|sess1|TXID:mytxid", "!sender1")
        rpc_client.broadcast_transaction.assert_not_called()
        self.assertEqual(receiver.get_active_sessions(), [])

    def test_retransmitted_last_chunk_after_broadcast_failure_resends_cached_nack(self):
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = (None, "insufficient fee for this tx")
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.reset_mock()
        rpc_client.broadcast_transaction.reset_mock()
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.assert_called_once_with("BTC_NACK|sess1|Insufficient fee", "!sender1")
        rpc_client.broadcast_transaction.assert_not_called()

    def test_retransmitted_last_chunk_when_rpc_not_connected_resends_cached_nack(self):
        transport = Mock(spec=BaseTransport)
        receiver = TransactionReceiver(transport, None)
        handler = transport.set_message_handler.call_args[0][0]
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.reset_mock()
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.assert_called_once_with("BTC_NACK|sess1|Bitcoin RPC not connected", "!sender1")

    def test_different_sender_with_same_session_id_not_confused(self):
        """Session IDs are only unique per-sender - a retransmission cache
        keyed on session_id alone would leak one sender's cached reply to
        an unrelated sender who happens to reuse the same random id."""
        receiver, transport, rpc_client, handler = make_receiver()
        rpc_client.broadcast_transaction.return_value = ("firsttxid", None)
        handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

        transport.send.reset_mock()
        rpc_client.broadcast_transaction.reset_mock()
        rpc_client.broadcast_transaction.return_value = ("secondtxid", None)
        handler("BTC_TX|sess1|1/1|beefdead", "!sender2")

        rpc_client.broadcast_transaction.assert_called_once_with("beefdead")
        final_call = transport.send.call_args_list[-1]
        self.assertEqual(final_call.args[0], "BTC_ACK|sess1|TXID:secondtxid")
        self.assertEqual(final_call.args[1], "!sender2")

    def test_cache_entry_expires_after_grace_period(self):
        with patch("server.receiver.time.time") as mock_time:
            mock_time.return_value = 1000.0
            receiver, transport, rpc_client, handler = make_receiver(
                completed_session_grace_seconds=100
            )
            rpc_client.broadcast_transaction.return_value = ("mytxid", None)
            handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")
            rpc_client.broadcast_transaction.assert_called_once()

            mock_time.return_value = 1000.0 + 101  # past the grace period
            rpc_client.broadcast_transaction.reset_mock()
            handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")

            # Cache entry expired - treated as a genuinely new session, broadcasts again
            rpc_client.broadcast_transaction.assert_called_once()

    def test_check_timeouts_prunes_expired_completed_sessions(self):
        with patch("server.receiver.time.time") as mock_time:
            mock_time.return_value = 1000.0
            receiver, transport, rpc_client, handler = make_receiver(
                completed_session_grace_seconds=100
            )
            rpc_client.broadcast_transaction.return_value = ("mytxid", None)
            handler("BTC_TX|sess1|1/1|deadbeef", "!sender1")
            self.assertEqual(len(receiver._completed_sessions), 1)

            mock_time.return_value = 1000.0 + 101
            receiver.check_timeouts()

            self.assertEqual(len(receiver._completed_sessions), 0)


if __name__ == "__main__":
    unittest.main()
