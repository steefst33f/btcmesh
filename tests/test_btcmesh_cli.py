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

if __name__ == '__main__':
    unittest.main() 