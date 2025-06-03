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
        code, out, err = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn(dest, out)
        self.assertIn(tx_hex, out)
        self.assertIn('Arguments parsed successfully', out)

    def test_missing_destination(self):
        tx_hex = 'deadbeefcafebabe'
        code, out, err = self.run_cli(['-tx', tx_hex, '--dry-run'])
        self.assertNotEqual(code, 0)
        self.assertIn('usage', out.lower() + err.lower())

    def test_missing_tx(self):
        dest = '!abcdef12'
        code, out, err = self.run_cli(['-d', dest, '--dry-run'])
        self.assertNotEqual(code, 0)
        self.assertIn('usage', out.lower() + err.lower())

    def test_invalid_hex(self):
        dest = '!abcdef12'
        bad_hex = 'deadbeefZZZ'
        code, out, err = self.run_cli(['-d', dest, '-tx', bad_hex, '--dry-run'])
        self.assertNotEqual(code, 0)
        self.assertIn('Invalid raw transaction hex', out + err)

    def test_odd_length_hex(self):
        dest = '!abcdef12'
        bad_hex = 'abcde'
        code, out, err = self.run_cli(['-d', dest, '-tx', bad_hex, '--dry-run'])
        self.assertNotEqual(code, 0)
        self.assertIn('Invalid raw transaction hex', out + err)

class TestBtcmeshCliStory63(unittest.TestCase):
    CHUNK_SIZE = 200  # hex chars

    def run_cli(self, args):
        cmd = [sys.executable, SCRIPT_PATH] + args
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr

    def test_single_chunk(self):
        dest = '!abcdef12'
        tx_hex = 'a' * 100  # 50 bytes, fits in one chunk
        code, out, err = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('BTC_TX|', out)
        self.assertIn('|1/1|', out)
        self.assertIn(tx_hex, out)

    def test_multi_chunk(self):
        dest = '!abcdef12'
        tx_hex = 'b' * 450  # 225 bytes, should be 3 chunks (200, 200, 50)
        code, out, err = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.startswith('BTC_TX|')]
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines, 1):
            self.assertIn(f'|{i}/3|', line)
        self.assertTrue(all(len(line.split('|')[-1]) <= self.CHUNK_SIZE for line in lines))
        self.assertIn(tx_hex[:200], lines[0])
        self.assertIn(tx_hex[200:400], lines[1])
        self.assertIn(tx_hex[400:], lines[2])

    def test_chunk_size_boundary(self):
        dest = '!abcdef12'
        tx_hex = 'c' * self.CHUNK_SIZE  # Exactly one chunk
        code, out, err = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('|1/1|', out)
        self.assertIn(tx_hex, out)

    def test_session_id_looks_unique(self):
        dest = '!abcdef12'
        tx_hex = 'd' * 100
        code1, out1, _ = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        code2, out2, _ = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        # Extract session IDs from BTC_TX|<session_id>|...
        import re
        sid1 = re.search(r'BTC_TX\|([^|]+)\|', out1)
        sid2 = re.search(r'BTC_TX\|([^|]+)\|', out2)
        self.assertIsNotNone(sid1)
        self.assertIsNotNone(sid2)
        self.assertNotEqual(sid1.group(1), sid2.group(1))
        self.assertTrue(len(sid1.group(1)) >= 8)

    def test_chunks_printed_in_order(self):
        dest = '!abcdef12'
        tx_hex = ''.join(f'{i%10}' for i in range(600))  # 3 chunks
        code, out, err = self.run_cli(['-d', dest, '-tx', tx_hex, '--dry-run'])
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.startswith('BTC_TX|')]
        # Chunks should be in order and reconstruct the original
        payloads = [line.split('|', 3)[-1] for line in lines]
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

if __name__ == '__main__':
    unittest.main() 