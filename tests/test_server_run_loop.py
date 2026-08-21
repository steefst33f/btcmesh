"""Tests for server/run_loop.py's shared build_receiver()/run_polling_loop()
(Issue 34). Relocated/adapted from tests/test_btcmesh_server_cli.py's
TestBuildReceiver - this logic used to live duplicated in
btcmesh_server_cli.py and btcmesh_server_gui.py; these tests now exercise
the shared module directly via a mock log callable instead of patching
server_logger.
"""
import logging
import unittest
from unittest.mock import MagicMock, patch

from server.receiver import BroadcastResult, ChunkReceived
from server.run_loop import (
    CHECK_TIMEOUTS_INTERVAL_SECONDS,
    LIVENESS_LOG_INTERVAL_SECONDS,
    build_receiver,
    run_polling_loop,
)


class TestBuildReceiver(unittest.TestCase):
    """Tests for build_receiver()'s callback wiring to `log` + history."""

    def _extract_callbacks(self, watchdog=None):
        history = MagicMock()
        watchdog = watchdog if watchdog is not None else MagicMock()
        log = MagicMock()
        with patch("server.run_loop.TransactionReceiver") as mock_receiver_cls:
            build_receiver(MagicMock(), MagicMock(), 300, history, watchdog, log)
            kwargs = mock_receiver_cls.call_args.kwargs
        return kwargs, history, log

    def test_wires_all_eight_callbacks_and_reassembler_timeout(self):
        with patch("server.run_loop.TransactionReceiver") as mock_receiver_cls, \
                patch("server.run_loop.TransactionReassembler") as mock_reassembler_cls:
            build_receiver(MagicMock(), MagicMock(), 300, MagicMock(), MagicMock(), MagicMock())

        mock_reassembler_cls.assert_called_once_with(timeout_seconds=300)
        kwargs = mock_receiver_cls.call_args.kwargs
        for name in (
            "on_chunk_received", "on_broadcast_started", "on_broadcast",
            "on_error", "on_wire_sent", "on_wire_received", "on_transport_error",
            "on_transport_success",
        ):
            self.assertIn(name, kwargs)
            self.assertTrue(callable(kwargs[name]))

    def test_on_transport_error_calls_watchdog_record_failure(self):
        watchdog = MagicMock()
        kwargs, _, _ = self._extract_callbacks(watchdog=watchdog)
        kwargs["on_transport_error"](RuntimeError("device wedged"))
        watchdog.record_failure.assert_called_once()

    def test_on_transport_success_calls_watchdog_record_success(self):
        watchdog = MagicMock()
        kwargs, _, _ = self._extract_callbacks(watchdog=watchdog)
        kwargs["on_transport_success"]()
        watchdog.record_success.assert_called_once()

    def test_on_chunk_received_logs_progress_when_not_last_chunk(self):
        kwargs, _, log = self._extract_callbacks()
        kwargs["on_chunk_received"](
            ChunkReceived(session_id="sess1", sender_id="!abc", chunk_num=1, total_chunks=3)
        )
        log.assert_any_call("[sess1] Received chunk 1/3 from !abc", logging.INFO, highlight=True)
        log.assert_any_call("[sess1] Requesting chunk 2/3...", logging.INFO, highlight=True)

    def test_on_chunk_received_logs_reassembly_success_on_last_chunk(self):
        kwargs, _, log = self._extract_callbacks()
        kwargs["on_chunk_received"](
            ChunkReceived(session_id="sess1", sender_id="!abc", chunk_num=3, total_chunks=3)
        )
        log.assert_any_call("[sess1] All 3 chunks received. Reassembly successful.", logging.INFO, highlight=True)

    def test_on_broadcast_started_logs_message(self):
        kwargs, _, log = self._extract_callbacks()
        kwargs["on_broadcast_started"]("sess1", "!abc")
        log.assert_any_call("[sess1] Broadcasting transaction to Bitcoin network...", logging.INFO, highlight=True)

    def test_on_broadcast_success_logs_and_records_history(self):
        kwargs, history, log = self._extract_callbacks()
        kwargs["on_broadcast"](BroadcastResult(
            session_id="sess1", sender_id="!abc", success=True, txid="txid123", raw_tx="deadbeef"
        ))
        log.assert_any_call("[sess1] Broadcast success. TXID: txid123", logging.INFO)
        history.add.assert_called_once_with(
            session_id="sess1", sender="!abc", status="success", txid="txid123", raw_tx="deadbeef"
        )

    def test_on_broadcast_failure_logs_error_and_records_history(self):
        kwargs, history, log = self._extract_callbacks()
        kwargs["on_broadcast"](BroadcastResult(
            session_id="sess1", sender_id="!abc", success=False, error="Insufficient fee", raw_tx="deadbeef"
        ))
        log.assert_any_call("[sess1] Broadcast failed: Insufficient fee", logging.ERROR)
        history.add.assert_called_once_with(
            session_id="sess1", sender="!abc", status="failed", error="Insufficient fee", raw_tx="deadbeef"
        )

    def test_on_error_logs_warning_and_records_history(self):
        kwargs, history, log = self._extract_callbacks()
        kwargs["on_error"]("sess1", "!abc", "Timed out")
        log.assert_any_call("[sess1] Error from !abc: Timed out", logging.WARNING)
        history.add.assert_called_once_with(
            session_id="sess1", sender="!abc", status="failed", error="Timed out", raw_tx=None
        )

    def test_on_wire_sent_logs_message(self):
        kwargs, _, log = self._extract_callbacks()
        kwargs["on_wire_sent"]("BTC_CHUNK_ACK|sess1|1|REQUEST_CHUNK|2")
        log.assert_any_call("  -> BTC_CHUNK_ACK|sess1|1|REQUEST_CHUNK|2", logging.INFO)

    def test_on_wire_received_logs_message(self):
        kwargs, _, log = self._extract_callbacks()
        kwargs["on_wire_received"]("BTC_TX|sess1|1/3|deadbeef")
        log.assert_any_call("  <- BTC_TX|sess1|1/3|deadbeef", logging.INFO)


class TestRunPollingLoop(unittest.TestCase):
    """Tests for run_polling_loop()'s timeout/liveness/watchdog scheduling."""

    def test_stops_immediately_when_stop_check_is_true(self):
        receiver = MagicMock()
        watchdog = MagicMock()
        with patch("server.run_loop.time.sleep") as mock_sleep:
            run_polling_loop(receiver, watchdog, log=MagicMock(), stop_check=lambda: True)
        mock_sleep.assert_not_called()
        watchdog.tick.assert_not_called()

    def test_tick_called_each_loop_iteration(self):
        receiver = MagicMock()
        watchdog = MagicMock()
        with patch("server.run_loop.time.sleep", side_effect=[None, None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=MagicMock())
        self.assertEqual(watchdog.tick.call_count, 3)

    def test_check_timeouts_called_after_interval_elapses(self):
        receiver = MagicMock()
        watchdog = MagicMock()
        with patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 100.0 + CHECK_TIMEOUTS_INTERVAL_SECONDS, 100.0 + CHECK_TIMEOUTS_INTERVAL_SECONDS]), \
                patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=MagicMock())
        receiver.check_timeouts.assert_called_once()

    def test_check_timeouts_not_called_before_interval_elapses(self):
        receiver = MagicMock()
        watchdog = MagicMock()
        with patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 105.0, 105.0]), \
                patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=MagicMock())
        receiver.check_timeouts.assert_not_called()

    def test_liveness_log_fires_after_interval_elapses(self):
        receiver = MagicMock()
        receiver.get_active_sessions.return_value = ["s1", "s2"]
        watchdog = MagicMock()
        log = MagicMock()
        with patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 100.0 + LIVENESS_LOG_INTERVAL_SECONDS, 100.0 + LIVENESS_LOG_INTERVAL_SECONDS]), \
                patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=log)
        log.assert_any_call("Server heartbeat: alive, listening. 2 active session(s).", logging.INFO)

    def test_liveness_log_does_not_fire_before_interval_elapses(self):
        receiver = MagicMock()
        receiver.get_active_sessions.return_value = []
        watchdog = MagicMock()
        log = MagicMock()
        with patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 150.0, 150.0]), \
                patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=log)
        for call in log.call_args_list:
            self.assertNotIn("heartbeat", call.args[0])

    def test_on_tick_called_with_active_sessions_every_iteration(self):
        receiver = MagicMock()
        receiver.get_active_sessions.return_value = ["s1"]
        watchdog = MagicMock()
        on_tick = MagicMock()
        with patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=MagicMock(), on_tick=on_tick)
        self.assertEqual(on_tick.call_count, 2)
        on_tick.assert_any_call(["s1"])

    def test_on_tick_omitted_does_not_call_get_active_sessions_every_iteration(self):
        """The CLI has no live display and passes no on_tick - it should
        not pay for a get_active_sessions() call every second just for
        that, only when actually needed for the liveness log."""
        receiver = MagicMock()
        receiver.get_active_sessions.return_value = []
        watchdog = MagicMock()
        with patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 105.0, 105.0]), \
                patch("server.run_loop.time.sleep", side_effect=[None, RuntimeError("stop")]):
            with self.assertRaises(RuntimeError):
                run_polling_loop(receiver, watchdog, log=MagicMock())
        receiver.get_active_sessions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
