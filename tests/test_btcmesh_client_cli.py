"""Tests for btcmesh_client_cli.py — thin CLI entry point.

Covers only genuine CLI-layer concerns: argument parsing/validation, dry-run
preview output, device connection/port resolution, and exit codes. Business
logic (chunking, ARQ, retries, ACK/NACK handling) is tested in
tests/test_client_sender.py and tests/test_meshtastic_serial_transport.py.
"""
import unittest
from unittest.mock import patch, MagicMock

from transport.base import TransportConnectionError
from client.sender import SendResult
import btcmesh_client_cli as cli


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args()."""

    def test_valid_args_parse_correctly(self):
        args = cli.parse_args(["-d", "!abcdef12", "-tx", "deadbeef"])
        self.assertEqual(args.destination, "!abcdef12")
        self.assertEqual(args.tx, "deadbeef")
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.port)

    def test_dry_run_and_port_flags_parse_correctly(self):
        args = cli.parse_args([
            "-d", "!abcdef12", "-tx", "deadbeef", "--dry-run", "-p", "/dev/ttyUSB0",
        ])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.port, "/dev/ttyUSB0")

    def test_missing_destination_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(["-tx", "deadbeef"])

    def test_missing_tx_raises_system_exit(self):
        with self.assertRaises(SystemExit):
            cli.parse_args(["-d", "!abcdef12"])


class TestCliMainValidation(unittest.TestCase):
    """Tests for cli_main()'s hex validation path."""

    def test_invalid_hex_prints_error_and_returns_1(self):
        with patch("builtins.print") as mock_print:
            code = cli.cli_main(["-d", "!abcdef12", "-tx", "zz"])
        self.assertEqual(code, 1)
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("Invalid raw transaction hex", printed)

    def test_odd_length_hex_prints_error_and_returns_1(self):
        with patch("builtins.print") as mock_print:
            code = cli.cli_main(["-d", "!abcdef12", "-tx", "abc"])
        self.assertEqual(code, 1)
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("Invalid raw transaction hex", printed)

    def test_invalid_hex_does_not_attempt_connection(self):
        with patch("btcmesh_client_cli.MeshtasticSerialTransport") as mock_transport_cls, \
             patch("builtins.print"):
            cli.cli_main(["-d", "!abcdef12", "-tx", "zz"])
        mock_transport_cls.assert_not_called()


class TestCliMainDryRun(unittest.TestCase):
    """Tests for cli_main() --dry-run path (run_preview)."""

    def test_dry_run_prints_chunk_preview(self):
        tx_hex = "a" * 450  # 3 chunks at DEFAULT_CHUNK_SIZE=170
        with patch("builtins.print") as mock_print:
            code = cli.cli_main(["-d", "!abcdef12", "-tx", tx_hex, "--dry-run"])
        self.assertEqual(code, 0)
        printed_lines = [
            str(c.args[0]) for c in mock_print.call_args_list
            if str(c.args[0]).startswith("BTC_TX|")
        ]
        self.assertEqual(len(printed_lines), 3)
        for i, line in enumerate(printed_lines, 1):
            self.assertIn(f"|{i}/3|", line)

    def test_dry_run_does_not_connect_to_device(self):
        with patch("btcmesh_client_cli.MeshtasticSerialTransport") as mock_transport_cls, \
             patch("builtins.print"):
            code = cli.cli_main(["-d", "!abcdef12", "-tx", "deadbeef", "--dry-run"])
        self.assertEqual(code, 0)
        mock_transport_cls.assert_not_called()


class TestRunSendConnection(unittest.TestCase):
    """Tests for run_send()'s device connection / port resolution."""

    def test_connection_failure_prints_error_and_returns_2(self):
        with patch("btcmesh_client_cli.MeshtasticSerialTransport") as mock_transport_cls, \
             patch("btcmesh_client_cli.TransactionSender") as mock_sender_cls, \
             patch("builtins.print") as mock_print:
            mock_transport = mock_transport_cls.return_value
            mock_transport.connect.side_effect = TransportConnectionError("no device found")

            code = cli.run_send("!abcdef12", "deadbeef")

        self.assertEqual(code, 2)
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("Failed to connect", printed)
        mock_sender_cls.assert_not_called()

    def test_explicit_port_overrides_env(self):
        with patch("btcmesh_client_cli.MeshtasticSerialTransport") as mock_transport_cls, \
             patch("btcmesh_client_cli.TransactionSender") as mock_sender_cls, \
             patch("btcmesh_client_cli.get_meshtastic_serial_port", return_value="/dev/env_port"), \
             patch("builtins.print"):
            mock_transport = mock_transport_cls.return_value
            mock_sender = mock_sender_cls.return_value
            mock_sender.send_transaction.return_value = SendResult(
                success=True, session_id="abc12", txid="txid123"
            )

            cli.run_send("!abcdef12", "deadbeef", port="/dev/explicit_port")

        mock_transport.connect.assert_called_once_with("/dev/explicit_port")

    def test_omitted_port_falls_back_to_env(self):
        with patch("btcmesh_client_cli.MeshtasticSerialTransport") as mock_transport_cls, \
             patch("btcmesh_client_cli.TransactionSender") as mock_sender_cls, \
             patch("btcmesh_client_cli.get_meshtastic_serial_port", return_value="/dev/env_port"), \
             patch("builtins.print"):
            mock_transport = mock_transport_cls.return_value
            mock_sender = mock_sender_cls.return_value
            mock_sender.send_transaction.return_value = SendResult(
                success=True, session_id="abc12", txid="txid123"
            )

            cli.run_send("!abcdef12", "deadbeef")

        mock_transport.connect.assert_called_once_with("/dev/env_port")


class TestRunSendResult(unittest.TestCase):
    """Tests for run_send()'s handling of the SendResult from TransactionSender."""

    def _patch_transport_and_sender(self, send_result=None, send_side_effect=None):
        transport_patch = patch("btcmesh_client_cli.MeshtasticSerialTransport")
        sender_patch = patch("btcmesh_client_cli.TransactionSender")
        mock_transport_cls = transport_patch.start()
        mock_sender_cls = sender_patch.start()
        self.addCleanup(transport_patch.stop)
        self.addCleanup(sender_patch.stop)

        mock_transport = mock_transport_cls.return_value
        mock_sender = mock_sender_cls.return_value
        if send_side_effect is not None:
            mock_sender.send_transaction.side_effect = send_side_effect
        else:
            mock_sender.send_transaction.return_value = send_result
        return mock_transport, mock_sender

    def test_successful_send_prints_txid_and_returns_0(self):
        mock_transport, _ = self._patch_transport_and_sender(
            send_result=SendResult(success=True, session_id="abc12", txid="txid123")
        )
        with patch("builtins.print") as mock_print:
            code = cli.run_send("!abcdef12", "deadbeef")

        self.assertEqual(code, 0)
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("txid123", printed)
        mock_transport.disconnect.assert_called_once()

    def test_failed_send_prints_error_and_returns_1(self):
        mock_transport, _ = self._patch_transport_and_sender(
            send_result=SendResult(success=False, session_id="abc12", error="Insufficient fee")
        )
        with patch("builtins.print") as mock_print:
            code = cli.run_send("!abcdef12", "deadbeef")

        self.assertEqual(code, 1)
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list)
        self.assertIn("Insufficient fee", printed)
        mock_transport.disconnect.assert_called_once()

    def test_disconnects_even_when_send_transaction_raises(self):
        mock_transport, _ = self._patch_transport_and_sender(
            send_side_effect=RuntimeError("boom")
        )
        with patch("builtins.print"):
            with self.assertRaises(RuntimeError):
                cli.run_send("!abcdef12", "deadbeef")

        mock_transport.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
