"""Tests for core/transaction_parser.py's raw transaction decoding and
basic sanity-check validation.

Relocated from tests/test_btcmesh_server.py (Story 23.3) - these tests
exercise core.transaction_parser directly and have no dependency on
btcmesh_server.py, they were just historically written before this logic
was extracted into its own core/ module.
"""
import unittest


class TestTransactionDecodeStory23(unittest.TestCase):
    def setUp(self):
        from core.transaction_parser import decode_raw_transaction_hex

        self.decode = decode_raw_transaction_hex

    def test_valid_raw_transaction_hex(self):
        """Given a valid raw transaction hex, When decoded, Then it returns a dict with fields."""
        # This is a minimal valid Bitcoin tx (version 1, 1 input, 1 output, locktime 0)
        # 01000000 (version 1)
        # 01 (input count)
        # 00..00 (32 bytes prev txid) + 00000000 (vout) + 00 (script len) + ffffffff (sequence)
        # 01 (output count)
        # 00e1f50500000000 (8 bytes value = 1 BTC)
        # 00 (script len)
        # 00000000 (locktime)
        raw_hex = (
            "01000000"
            + "01"
            + "00" * 32
            + "00000000"
            + "00"
            + "ffffffff"
            + "01"
            + "00e1f50500000000"
            + "00"
            + "00000000"
        )
        result = self.decode(raw_hex)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["input_count"], 1)
        self.assertEqual(result["output_count"], 1)
        self.assertEqual(result["locktime"], 0)

    def test_malformed_raw_transaction_hex(self):
        """Given a malformed raw transaction hex, When decoded, Then it raises ValueError and logs error."""
        bad_hex = "deadbeef"  # Too short to be a valid tx
        with self.assertRaises(ValueError):
            self.decode(bad_hex)


class TestTransactionSanityChecksStory31(unittest.TestCase):
    def setUp(self):
        self.valid_tx = {
            "version": 1,
            "input_count": 1,
            "output_count": 1,
            "locktime": 0,
        }
        self.no_inputs_tx = {
            "version": 1,
            "input_count": 0,
            "output_count": 1,
            "locktime": 0,
        }
        self.no_outputs_tx = {
            "version": 1,
            "input_count": 1,
            "output_count": 0,
            "locktime": 0,
        }

    def test_no_inputs_fails_validation(self):
        """Given a decoded transaction with zero inputs, When validated, Then it fails and NACK is prepared."""
        from core.transaction_parser import basic_sanity_check

        valid, error = basic_sanity_check(self.no_inputs_tx)
        self.assertFalse(valid)
        self.assertIn("No inputs", error)

    def test_no_outputs_fails_validation(self):
        """Given a decoded transaction with zero outputs, When validated, Then it fails and NACK is prepared."""
        from core.transaction_parser import basic_sanity_check

        valid, error = basic_sanity_check(self.no_outputs_tx)
        self.assertFalse(valid)
        self.assertIn("No outputs", error)

    def test_valid_tx_passes_validation(self):
        """Given a decoded transaction with at least one input and one output, When validated, Then it passes."""
        from core.transaction_parser import basic_sanity_check

        valid, error = basic_sanity_check(self.valid_tx)
        self.assertTrue(valid)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
