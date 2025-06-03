import unittest
import subprocess
import sys
import os

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

if __name__ == '__main__':
    unittest.main() 