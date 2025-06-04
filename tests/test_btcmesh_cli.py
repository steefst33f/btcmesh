import unittest
import subprocess
import sys
import os
from unittest.mock import patch, MagicMock, call, ANY
from btcmesh_cli import cli_main

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), '..', 'btcmesh_cli.py')

class TestBtcmeshCliStory61(unittest.TestCase):
    def run_cli(self, args):
        """Helper to run the CLI script with args and return (exitcode, stdout, stderr)."""
        cmd = [sys.executable, SCRIPT_PATH] + args
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def test_valid_args(self):
        # Use dummy but valid-looking hex and dest
        dest = '!abcdef12'
        tx_hex = 'deadbeefcafebabe'
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn(dest, printed)
        self.assertIn(tx_hex, printed)
        self.assertIn('Arguments parsed successfully', printed)

    def test_missing_destination(self):
        tx_hex = 'deadbeefcafebabe'
        def fake_parse_args():
            print('usage: btcmesh_cli.py [-d DEST] -tx TX [--dry-run]')
            raise SystemExit(2)
        with patch('argparse.ArgumentParser.parse_args', side_effect=fake_parse_args), \
             patch('builtins.print') as mock_print:
            with self.assertRaises(SystemExit):
                cli_main(args=None)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('usage', printed.lower())

    def test_missing_tx(self):
        def fake_parse_args():
            print('usage: btcmesh_cli.py [-d DEST] -tx TX [--dry-run]')
            raise SystemExit(2)
        with patch('argparse.ArgumentParser.parse_args', side_effect=fake_parse_args), \
             patch('builtins.print') as mock_print:
            with self.assertRaises(SystemExit):
                cli_main(args=None)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('usage', printed.lower())

    def test_invalid_hex(self):
        dest = '!abcdef12'
        bad_hex = 'deadbeefZZZ'
        Args = type('Args', (), {'destination': dest, 'tx': bad_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print, self.assertRaises(ValueError):
            cli_main(args=Args)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('Invalid raw transaction hex', printed)

    def test_odd_length_hex(self):
        dest = '!abcdef12'
        bad_hex = 'abcde'
        Args = type('Args', (), {'destination': dest, 'tx': bad_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print, self.assertRaises(ValueError):
            cli_main(args=Args)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('Invalid raw transaction hex', printed)

class TestBtcmeshCliStory63(unittest.TestCase):
    CHUNK_SIZE = 170  # hex chars (85 bytes)

    def test_single_chunk(self):
        dest = '!abcdef12'
        tx_hex = 'a' * 100  # 50 bytes, fits in one chunk
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('BTC_TX|', printed)
        self.assertIn('|1/1|', printed)
        self.assertIn(tx_hex, printed)

    def test_multi_chunk(self):
        dest = '!abcdef12'
        tx_hex = 'b' * 450  # 225 bytes, should be 3 chunks (170, 170, 110)
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list if str(call.args[0]).startswith('BTC_TX|')]
        self.assertEqual(len(printed_lines), 3)
        for i, line in enumerate(printed_lines, 1):
            self.assertIn(f'|{i}/3|', line)
        self.assertTrue(all(len(line.split('|')[-1]) <= self.CHUNK_SIZE for line in printed_lines))
        self.assertIn(tx_hex[:170], printed_lines[0])
        self.assertIn(tx_hex[170:340], printed_lines[1])
        self.assertIn(tx_hex[340:], printed_lines[2])

    def test_chunk_size_boundary(self):
        dest = '!abcdef12'
        tx_hex = 'c' * self.CHUNK_SIZE  # Exactly one chunk
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed = '\n'.join(str(call.args[0]) for call in mock_print.call_args_list)
        self.assertIn('|1/1|', printed)
        self.assertIn(tx_hex, printed)

    def test_chunk_size_limit_enforced(self):
        dest = '!abcdef12'
        tx_hex = 'e' * 510  # 3 chunks: 170, 170, 170
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list if str(call.args[0]).startswith('BTC_TX|')]
        self.assertEqual(len(printed_lines), 3)
        for line in printed_lines:
            self.assertLessEqual(len(line.split('|')[-1]), self.CHUNK_SIZE)

    def test_session_id_looks_unique(self):
        dest = '!abcdef12'
        tx_hex = 'd' * 100
        Args1 = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        Args2 = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print1:
            cli_main(args=Args1)
        with patch('builtins.print') as mock_print2:
            cli_main(args=Args2)
        import re
        printed1 = '\n'.join(str(call.args[0]) for call in mock_print1.call_args_list)
        printed2 = '\n'.join(str(call.args[0]) for call in mock_print2.call_args_list)
        sid1 = re.search(r'BTC_TX\|([^|]+)\|', printed1)
        sid2 = re.search(r'BTC_TX\|([^|]+)\|', printed2)
        self.assertIsNotNone(sid1)
        self.assertIsNotNone(sid2)
        self.assertNotEqual(sid1.group(1), sid2.group(1))
        self.assertTrue(len(sid1.group(1)) >= 8)

    def test_chunks_printed_in_order(self):
        dest = '!abcdef12'
        tx_hex = ''.join(f'{i%10}' for i in range(510))  # 3 chunks
        Args = type('Args', (), {'destination': dest, 'tx': tx_hex, 'dry_run': True})
        with patch('builtins.print') as mock_print:
            code = cli_main(args=Args)
        self.assertEqual(code, 0)
        printed_lines = [str(call.args[0]) for call in mock_print.call_args_list if str(call.args[0]).startswith('BTC_TX|')]
        payloads = [line.split('|', 3)[-1] for line in printed_lines]
        self.assertEqual(''.join(payloads), tx_hex)

class TestMeshtasticCliInitializationStory62(unittest.TestCase):
    """
    TDD for Story 6.2: Meshtastic interface initialization in btcmesh-cli.py
    Covers:
      - Successful connection (auto-detect and config port)
      - Device not found
      - Import error (meshtastic not installed)
      - Logging of all attempts and errors
    """
    def setUp(self):
        # Patch meshtastic and its components in sys.modules
        self.mock_meshtastic_module = MagicMock()
        self.mock_serial_interface_module = MagicMock()
        self.MockMeshtasticSerialInterfaceClass = MagicMock()
        self.mock_serial_interface_module.SerialInterface = self.MockMeshtasticSerialInterfaceClass
        self.mock_meshtastic_module.serial_interface = self.mock_serial_interface_module
        self.MockNoDeviceError = type('NoDeviceError', (Exception,), {})
        self.MockMeshtasticError = type('MeshtasticError', (Exception,), {})
        self.mock_meshtastic_module.NoDeviceError = self.MockNoDeviceError
        self.mock_meshtastic_module.MeshtasticError = self.MockMeshtasticError
        self.sys_modules_patcher = patch.dict(sys.modules, {
            'meshtastic': self.mock_meshtastic_module,
            'meshtastic.serial_interface': self.mock_serial_interface_module,
        })
        self.sys_modules_patcher.start()
        # Patch config loader for port
        self.config_loader_patcher = patch('core.config_loader.get_meshtastic_serial_port')
        self.mock_get_serial_port = self.config_loader_patcher.start()
        # Patch logger setup for CLI
        self.logger_patcher = patch('core.logger_setup.setup_logger', return_value=MagicMock())
        self.mock_setup_logger = self.logger_patcher.start()
    def tearDown(self):
        self.sys_modules_patcher.stop()
        self.config_loader_patcher.stop()
        self.logger_patcher.stop()
    def test_successful_autodetect(self):
        self.mock_get_serial_port.return_value = None
        mock_iface = self.MockMeshtasticSerialInterfaceClass.return_value
        mock_iface.devicePath = '/dev/ttyUSB0'
        # Simulate CLI init function (to be implemented)
        # Should log attempt and success
        # ...
        # self.mock_setup_logger().info.assert_any_call('Attempting to initialize Meshtastic interface (auto-detect)...')
        # self.mock_setup_logger().info.assert_any_call('Meshtastic interface initialized successfully. Device: /dev/ttyUSB0')
    def test_successful_with_config_port(self):
        self.mock_get_serial_port.return_value = '/dev/ttyS0'
        mock_iface = self.MockMeshtasticSerialInterfaceClass.return_value
        mock_iface.devicePath = '/dev/ttyS0'
        # Simulate CLI init function (to be implemented)
        # Should log attempt and success
        # ...
    def test_no_device_error(self):
        self.mock_get_serial_port.return_value = None
        self.MockMeshtasticSerialInterfaceClass.side_effect = self.MockNoDeviceError('No device')
        # Simulate CLI init function (to be implemented)
        # Should log error and exit
        # ...
    def test_import_error(self):
        # Remove meshtastic from sys.modules and patch import to raise ImportError
        with patch.dict('sys.modules', {'meshtastic': None, 'meshtastic.serial_interface': None}):
            with patch('builtins.__import__', side_effect=ImportError):
                # Simulate CLI init function (to be implemented)
                # Should log error and exit
                # ...
                pass
    def test_logging_on_all_attempts(self):
        # Should log every connection attempt and error
        # ...
        pass

class TestMeshtasticCliChunkedSendingStory63(unittest.TestCase):
    """
    TDD for Story 6.3: Chunked transaction sending via Meshtastic in CLI.
    Covers multi-chunk, single-chunk, send errors, and logging.
    """
    def setUp(self):
        self.mock_iface = MagicMock()
        self.mock_logger = MagicMock()
    def make_args(self, dest, tx_hex, dry_run=False):
        return type('Args', (), {
            'destination': dest,
            'tx': tx_hex,
            'dry_run': dry_run
        })()
    def assert_printed_substring(self, mock_print, substring):
        found = any(substring in str(call.args[0]) for call in mock_print.call_args_list)
        assert found, f"Did not find print call containing: {substring}"
    def test_multi_chunk_transaction_sends_all(self):
        dest = '!abcdef12'
        tx_hex = 'a' * 450  # 3 chunks
        self.mock_iface.sendText.return_value = None
        args = self.make_args(dest, tx_hex)
        with patch('builtins.print') as mock_print:
            ret = cli_main(args=args, injected_iface=self.mock_iface, injected_logger=self.mock_logger)
        self.assertEqual(ret, 0)
        self.assertEqual(self.mock_iface.sendText.call_count, 3)
        self.assert_printed_substring(mock_print, 'Sent chunk 1/3 for session')
        self.assert_printed_substring(mock_print, 'Sent chunk 2/3 for session')
        self.assert_printed_substring(mock_print, 'Sent chunk 3/3 for session')
        self.assert_printed_substring(mock_print, 'All transaction chunks sent for session')
    def test_single_chunk_transaction_sends_one(self):
        dest = '!abcdef12'
        tx_hex = 'b' * 100  # 1 chunk
        self.mock_iface.sendText.return_value = None
        args = self.make_args(dest, tx_hex)
        with patch('builtins.print') as mock_print:
            ret = cli_main(args=args, injected_iface=self.mock_iface, injected_logger=self.mock_logger)
        self.assertEqual(ret, 0)
        self.assertEqual(self.mock_iface.sendText.call_count, 1)
        self.assert_printed_substring(mock_print, 'Sent chunk 1/1 for session')
        self.assert_printed_substring(mock_print, 'All transaction chunks sent for session')
    def test_error_sending_chunk_logs_and_prints(self):
        dest = '!abcdef12'
        tx_hex = 'c' * 300  # 2 chunks
        def sendText_side_effect(*args, **kwargs):
            # Raise on first chunk
            raise Exception('Send failed')
        self.mock_iface.sendText.side_effect = sendText_side_effect
        args = self.make_args(dest, tx_hex)
        with patch('builtins.print') as mock_print, self.assertRaises(Exception):
            cli_main(args=args, injected_iface=self.mock_iface, injected_logger=self.mock_logger)
        self.assert_printed_substring(mock_print, 'Error sending chunk 1/2 for session')
        found_log = any('Error sending chunk 1/2 for session' in str(call.args[0]) for call in self.mock_logger.error.call_args_list)
        assert found_log, 'Did not find logger.error call containing: Error sending chunk 1/2 for session'
    def test_logging_on_all_chunking_and_sending(self):
        dest = '!abcdef12'
        tx_hex = 'd' * 400  # 2 chunks
        self.mock_iface.sendText.return_value = None
        args = self.make_args(dest, tx_hex)
        cli_main(args=args, injected_iface=self.mock_iface, injected_logger=self.mock_logger)
        self.mock_logger.info.assert_any_call(ANY)

class TestMeshtasticCliAckNackListeningStory64(unittest.TestCase):
    """
    TDD for Story 6.4: Listen for ACK/NACK in btcmesh-cli.py.
    Covers: success, error, timeout, unrelated messages, and logging.
    """
    def setUp(self):
        self.mock_iface = MagicMock()
        self.mock_logger = MagicMock()
        self.session_id = 'testsession123'
        self.dest = '!abcdef12'
        self.tx_hex = 'a' * 100
    def make_args(self, dest, tx_hex, dry_run=False):
        return type('Args', (), {
            'destination': dest,
            'tx': tx_hex,
            'dry_run': dry_run
        })()
    def test_receives_btc_ack_for_session(self):
        # Simulate receiving BTC_ACK for the session
        txid = 'abc123txid'
        ack_msg = f'BTC_ACK|{self.session_id}|SUCCESS|TXID:{txid}'
        # Mock message receiver yields the ACK message
        def mock_message_receiver(timeout, session_id):
            yield ack_msg
        args = self.make_args(self.dest, self.tx_hex)
        args.session_id = self.session_id  # Inject session_id for deterministic test
        # Patch print and call cli_main with injected message receiver
        with patch('builtins.print') as mock_print:
            ret = cli_main(args=args, injected_iface=self.mock_iface, injected_logger=self.mock_logger, injected_message_receiver=mock_message_receiver)
        # Should print success with TXID and return 0
        found = any(f'Transaction successfully broadcast by relay. TXID: {txid}' in str(call.args[0]) for call in mock_print.call_args_list)
        assert found, 'Did not print success message with TXID'
        self.assertEqual(ret, 0)
    def test_receives_btc_nack_for_session(self):
        # Simulate receiving BTC_NACK for the session
        # Should print error with details and exit 1
        pass
    def test_timeout_waiting_for_ack_nack(self):
        # Simulate no ACK/NACK received within timeout
        # Should print timeout message and exit 2
        pass
    def test_ignores_unrelated_messages(self):
        # Simulate receiving unrelated messages (wrong session or not ACK/NACK)
        # Should not exit or print success/error for those
        pass
    def test_logging_on_ack_nack_and_timeout(self):
        # Should log all received ACK/NACK and timeouts
        pass

if __name__ == '__main__':
    unittest.main() 