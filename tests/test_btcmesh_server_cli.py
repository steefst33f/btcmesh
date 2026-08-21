"""Tests for btcmesh_server_cli.py — thin CLI entry point.

Covers only genuine CLI-layer concerns: argument parsing, device
connection/port resolution, RPC-failure tolerance, and shutdown behavior.
The shared callback-wiring/polling-loop logic (Issue 34) is tested
directly in tests/test_server_run_loop.py; business logic (chunk
reassembly, ACK/NACK, RPC broadcast) is tested in
tests/test_server_receiver.py and tests/test_meshtastic_serial_transport.py.
"""
import logging
import unittest
from unittest.mock import patch, MagicMock

from transport.base import TransportConnectionError
import btcmesh_server_cli as cli


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args()."""

    def test_port_flag_parses_correctly(self):
        args = cli.parse_args(["-p", "/dev/ttyUSB0"])
        self.assertEqual(args.port, "/dev/ttyUSB0")

    def test_omitted_port_defaults_to_none(self):
        args = cli.parse_args([])
        self.assertIsNone(args.port)


class TestRunServerConnection(unittest.TestCase):
    """Tests for run_server()'s Meshtastic connection / port resolution."""

    def test_connection_failure_logs_error_and_returns_2(self):
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch("btcmesh_server_cli.load_app_config"), \
                patch("btcmesh_server_cli.BitcoinRPCClient") as mock_rpc_cls, \
                patch("btcmesh_server_cli.build_receiver") as mock_build_receiver, \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            mock_transport = mock_transport_cls.return_value
            mock_transport.connect.side_effect = TransportConnectionError("no device found")

            code = cli.run_server()

        self.assertEqual(code, 2)
        mock_logger.error.assert_any_call("Failed to connect to Meshtastic device: no device found")
        mock_rpc_cls.assert_not_called()
        mock_build_receiver.assert_not_called()

    def _patch_successful_startup(self):
        """Patch everything needed for run_server() to get past connection
        setup and into the main loop. Does NOT patch time.sleep - callers
        must do that themselves to end the otherwise-infinite loop, since
        how/when that happens is usually the actual point of the test."""
        patches = [
            patch("btcmesh_server_cli.load_app_config"),
            patch("btcmesh_server_cli.load_bitcoin_rpc_config", return_value={}),
            patch("btcmesh_server_cli.BitcoinRPCClient"),
            patch("btcmesh_server_cli.load_reassembly_timeout", return_value=(300, "default")),
            patch("btcmesh_server_cli.TransactionHistory"),
            patch("btcmesh_server_cli.build_receiver"),
            patch(
                "btcmesh_server_cli.build_device_watchdog",
                return_value=(MagicMock(), None),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_explicit_port_overrides_env(self):
        self._patch_successful_startup()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/env_port"), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt):
            # time.sleep raising KeyboardInterrupt on the first loop tick just
            # ends the otherwise-infinite loop so this test can return -
            # that's not what's being tested here, see
            # test_keyboard_interrupt_disconnects_and_returns_0 for that.
            mock_transport = mock_transport_cls.return_value
            code = cli.run_server(port="/dev/explicit_port")

        self.assertEqual(code, 0)
        mock_transport.connect.assert_called_once_with("/dev/explicit_port")

    def test_omitted_port_falls_back_to_env(self):
        self._patch_successful_startup()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/env_port"), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt):
            mock_transport = mock_transport_cls.return_value
            code = cli.run_server()

        self.assertEqual(code, 0)
        mock_transport.connect.assert_called_once_with("/dev/env_port")

    def test_keyboard_interrupt_disconnects_and_returns_0(self):
        """Given the server is already running its main loop (has completed
        at least one full tick), When a KeyboardInterrupt (Ctrl+C) arrives,
        Then it disconnects the transport and returns 0 instead of letting
        the exception propagate."""
        self._patch_successful_startup()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch("server.run_loop.time.sleep", side_effect=[None, KeyboardInterrupt]) as mock_sleep:
            # First call succeeds (one full loop tick completes normally =
            # "the server is running"); the second call raises, simulating
            # Ctrl+C arriving *while it's running* rather than on the very
            # first instruction, which would be ambiguous with "it never
            # actually started."
            mock_transport = mock_transport_cls.return_value
            code = cli.run_server()

        # Proves the loop really did complete a tick before being
        # interrupted, not just that run_server() happened to return 0.
        self.assertEqual(mock_sleep.call_count, 2)
        self.assertEqual(code, 0)
        mock_transport.disconnect.assert_called_once()


class TestRunServerDeviceWatchdog(unittest.TestCase):
    """Tests for run_server()'s DeviceWatchdog wiring (Story 26.5)."""

    def _patch_successful_startup(self):
        patches = [
            patch("btcmesh_server_cli.load_app_config"),
            patch("btcmesh_server_cli.load_bitcoin_rpc_config", return_value={}),
            patch("btcmesh_server_cli.BitcoinRPCClient"),
            patch("btcmesh_server_cli.load_reassembly_timeout", return_value=(300, "default")),
            patch("btcmesh_server_cli.TransactionHistory"),
            patch("btcmesh_server_cli.build_receiver"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_tick_called_each_loop_iteration(self):
        self._patch_successful_startup()
        mock_watchdog = MagicMock()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    return_value=(mock_watchdog, None),
                ), \
                patch(
                    "server.run_loop.time.sleep",
                    side_effect=[None, None, KeyboardInterrupt],
                ):
            cli.run_server()

        self.assertEqual(mock_watchdog.tick.call_count, 3)

    def test_logs_enabled_when_power_control_configured(self):
        self._patch_successful_startup()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    return_value=(MagicMock(), MagicMock()),
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()

        mock_logger.info.assert_any_call("Automatic device-recovery enabled via relay.")

    def test_logs_disabled_when_power_control_not_configured(self):
        self._patch_successful_startup()
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    return_value=(MagicMock(), None),
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()

        mock_logger.info.assert_any_call(
            "RELAY_SERIAL_PORT not configured - automatic device-wedge "
            "recovery is disabled (wedge detection still logs, but won't "
            "recover on its own)."
        )

    def test_on_recovery_attempt_logs_warning(self):
        self._patch_successful_startup()
        captured = {}

        def fake_build_device_watchdog(transport, **kwargs):
            captured.update(kwargs)
            return MagicMock(), None

        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    side_effect=fake_build_device_watchdog,
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()
            captured["on_recovery_attempt"]()

        mock_logger.warning.assert_any_call(
            "Device appears wedged - attempting automatic recovery..."
        )

    def test_on_recovered_logs_new_path(self):
        self._patch_successful_startup()
        captured = {}

        def fake_build_device_watchdog(transport, **kwargs):
            captured.update(kwargs)
            return MagicMock(), None

        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    side_effect=fake_build_device_watchdog,
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()
            from core.device_watchdog import RecoveryOutcome
            captured["on_recovered"](RecoveryOutcome(success=True, new_device_path="/dev/ttyNEW"))

        mock_logger.info.assert_any_call("Device recovered. Reconnected at /dev/ttyNEW.")

    def test_on_recovery_failed_logs_error(self):
        self._patch_successful_startup()
        captured = {}

        def fake_build_device_watchdog(transport, **kwargs):
            captured.update(kwargs)
            return MagicMock(), None

        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    side_effect=fake_build_device_watchdog,
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()
            from core.device_watchdog import RecoveryOutcome
            captured["on_recovery_failed"](
                RecoveryOutcome(success=False, error="Power cycle failed: no relay")
            )

        mock_logger.error.assert_any_call(
            "Automatic device recovery failed: Power cycle failed: no relay"
        )


class TestRunServerLivenessLog(unittest.TestCase):
    """Tests for run_server()'s periodic liveness log (Story 28.2 / Issue 21)."""

    def _patch_successful_startup(self):
        patches = [
            patch("btcmesh_server_cli.load_app_config"),
            patch("btcmesh_server_cli.load_bitcoin_rpc_config", return_value={}),
            patch("btcmesh_server_cli.BitcoinRPCClient"),
            patch("btcmesh_server_cli.load_reassembly_timeout", return_value=(300, "default")),
            patch("btcmesh_server_cli.TransactionHistory"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_liveness_log_fires_after_interval_elapses(self):
        self._patch_successful_startup()
        mock_receiver = MagicMock()
        mock_receiver.get_active_sessions.return_value = ["s1", "s2"]

        with patch("btcmesh_server_cli.build_receiver", return_value=mock_receiver), \
                patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch("btcmesh_server_cli.build_device_watchdog", return_value=(MagicMock(), None)), \
                patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 100.0, 401.0]), \
                patch("server.run_loop.time.sleep", side_effect=[None, KeyboardInterrupt]), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()

        # The liveness log flows through run_polling_loop() -> _log() ->
        # server_logger.log(level, message), not server_logger.info()
        # directly (Issue 34 - _log() is the shared sink for
        # server/run_loop.py's callbacks).
        mock_logger.log.assert_any_call(
            logging.INFO, "Server heartbeat: alive, listening. 2 active session(s)."
        )

    def test_liveness_log_does_not_fire_before_interval_elapses(self):
        self._patch_successful_startup()
        mock_receiver = MagicMock()
        mock_receiver.get_active_sessions.return_value = []

        with patch("btcmesh_server_cli.build_receiver", return_value=mock_receiver), \
                patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch("btcmesh_server_cli.build_device_watchdog", return_value=(MagicMock(), None)), \
                patch("server.run_loop.time.time", side_effect=[100.0, 100.0, 100.0, 150.0]), \
                patch("server.run_loop.time.sleep", side_effect=[None, KeyboardInterrupt]), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            cli.run_server()

        for call in mock_logger.log.call_args_list:
            self.assertNotIn("heartbeat", call.args[1])


class TestRunServerRpcFailure(unittest.TestCase):
    """Regression test for the exact bug fixed in Story 23.2's GUI equivalent:
    a failed RPC connection must not stop the server - Meshtastic keeps
    receiving/reassembling/ACKing chunks, only the eventual broadcast fails."""

    def test_rpc_failure_logs_error_and_builds_receiver_with_none_rpc_client(self):
        with patch("btcmesh_server_cli.MeshtasticSerialTransport") as mock_transport_cls, \
                patch("btcmesh_server_cli.get_meshtastic_serial_port", return_value="/dev/ttyUSB0"), \
                patch("btcmesh_server_cli.load_app_config"), \
                patch("btcmesh_server_cli.load_bitcoin_rpc_config", return_value={}), \
                patch("btcmesh_server_cli.BitcoinRPCClient", side_effect=Exception("connection refused")), \
                patch("btcmesh_server_cli.load_reassembly_timeout", return_value=(300, "default")), \
                patch("btcmesh_server_cli.TransactionHistory"), \
                patch("btcmesh_server_cli.build_receiver") as mock_build_receiver, \
                patch(
                    "btcmesh_server_cli.build_device_watchdog",
                    return_value=(MagicMock(), None),
                ), \
                patch("server.run_loop.time.sleep", side_effect=KeyboardInterrupt), \
                patch("btcmesh_server_cli.server_logger") as mock_logger:
            code = cli.run_server()

        self.assertEqual(code, 0)
        mock_logger.error.assert_any_call(
            "Failed to connect to Bitcoin Core RPC node: connection refused. Continuing without RPC connection."
        )
        mock_build_receiver.assert_called_once()
        # build_receiver(transport, rpc_client, reassembly_timeout, history) - positional
        self.assertIsNone(mock_build_receiver.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
