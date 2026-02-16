"""Tests for core/constants.py, core/message_types.py, and core/protocol.py.

All tests are pure — no mocking, no I/O, no patching needed because
the modules under test are pure functions and dataclasses.

protocol_spec.md defines the expected behavior of all functions, 
so these tests verify that the implementation is according to the specification.
version 1.0.0 of the protocol is the baseline for all tests, so if any 
constants or formats change in the future, these tests should fail and prompt 
an update to both the implementation and the tests.
"""
import unittest

from core.constants import (
    ACK_ALL_RECEIVED,
    ACK_OK,
    ACK_REQUEST_CHUNK,
    CHUNK_INDEX_DELIMITER,
    DEFAULT_CHUNK_SIZE,
    SESSION_ID_LENGTH,
    DEFAULT_REASSEMBLY_TIMEOUT,
    DEFAULT_ACK_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    CHUNK_DELIMITER,
    MSG_BTC_TX,
    MSG_CHUNK_ACK,
    MSG_ACK,
    MSG_NACK,
    MAX_NACK_LENGTH,
    STATUS_ERROR,
    STATUS_SUCCESS,
    TXID_PREFIX,
)
from core.message_types import (
    ChunkMessage,
    ChunkAckMessage,
    AckMessage,
    NackMessage,
    TransactionSession,
)
from core.protocol import (
    is_valid_hex,
    validate_transaction_hex,
    chunk_transaction,
    generate_session_id,
    create_session,
    get_chunk_message,
    parse_chunk,
    parse_chunk_ack,
    parse_ack,
    parse_nack,
    parse_message,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants(unittest.TestCase):
    """Verify protocol constants have expected values."""

    def test_default_chunk_size(self):
        self.assertEqual(DEFAULT_CHUNK_SIZE, 170)

    def test_session_id_length(self):
        self.assertEqual(SESSION_ID_LENGTH, 5)

    def test_default_ack_timeout(self):
        self.assertEqual(DEFAULT_ACK_TIMEOUT, 30)

    def test_default_max_retries(self):
        self.assertEqual(DEFAULT_MAX_RETRIES, 3)

    def test_default_reassembly_timeout(self):
        self.assertEqual(DEFAULT_REASSEMBLY_TIMEOUT, 300)

    def test_chunk_delimiter(self):
        self.assertEqual(CHUNK_DELIMITER, "|")

    def test_chunk_index_delimiter(self):
        self.assertEqual(CHUNK_INDEX_DELIMITER, "/")

    def test_max_nack_length(self):
        self.assertEqual(MAX_NACK_LENGTH, 200)

    def test_message_type_prefixes(self):
        self.assertEqual(MSG_BTC_TX, "BTC_TX")
        self.assertEqual(MSG_CHUNK_ACK, "BTC_CHUNK_ACK")
        self.assertEqual(MSG_ACK, "BTC_ACK")
        self.assertEqual(MSG_NACK, "BTC_NACK")

    def test_ack_sub_commands(self):
        self.assertEqual(ACK_OK, "OK")
        self.assertEqual(ACK_REQUEST_CHUNK, "REQUEST_CHUNK")
        self.assertEqual(ACK_ALL_RECEIVED, "ALL_CHUNKS_RECEIVED")

    def test_completion_statuses(self):
        self.assertEqual(STATUS_SUCCESS, "SUCCESS")
        self.assertEqual(STATUS_ERROR, "ERROR")
        self.assertEqual(TXID_PREFIX, "TXID:")


# ---------------------------------------------------------------------------
# Message type format() methods
# ---------------------------------------------------------------------------


class TestMessageTypeFormats(unittest.TestCase):
    """Verify format() methods produce correct wire strings."""

    def test_chunk_message_format(self):
        msg = ChunkMessage("abc12", 1, 3, "deadbeef")
        self.assertEqual(msg.format(), "BTC_TX|abc12|1/3|deadbeef")

    def test_chunk_message_format_single(self):
        msg = ChunkMessage("xyz99", 1, 1, "cafe")
        self.assertEqual(msg.format(), "BTC_TX|xyz99|1/1|cafe")

    def test_chunk_ack_request_next(self):
        msg = ChunkAckMessage("abc12", 1, request_next_chunk=2)
        self.assertEqual(msg.format(), "BTC_CHUNK_ACK|abc12|1|OK|REQUEST_CHUNK|2")

    def test_chunk_ack_all_received(self):
        msg = ChunkAckMessage("abc12", 3, all_received=True)
        self.assertEqual(msg.format(), "BTC_CHUNK_ACK|abc12|3|OK|ALL_CHUNKS_RECEIVED")

    def test_chunk_ack_bare(self):
        msg = ChunkAckMessage("abc12", 1)
        self.assertEqual(msg.format(), "BTC_CHUNK_ACK|abc12|1|OK")

    def test_ack_message_format(self):
        msg = AckMessage("abc12", "txid_hash_here")
        self.assertEqual(msg.format(), "BTC_ACK|abc12|SUCCESS|TXID:txid_hash_here")

    def test_nack_message_format(self):
        msg = NackMessage("abc12", "Invalid transaction")
        self.assertEqual(msg.format(), "BTC_NACK|abc12|ERROR|Invalid transaction")


class TestTransactionSession(unittest.TestCase):

    def test_total_chunks_property(self):
        session = TransactionSession("abc12", ["chunk1", "chunk2", "chunk3"])
        self.assertEqual(session.total_chunks, 3)

    def test_empty_chunks(self):
        session = TransactionSession("abc12", [])
        self.assertEqual(session.total_chunks, 0)

    def test_single_chunk(self):
        session = TransactionSession("abc12", ["only_one"])
        self.assertEqual(session.total_chunks, 1)


# ---------------------------------------------------------------------------
# Hex validation
# ---------------------------------------------------------------------------


class TestHexValidation(unittest.TestCase):

    def test_valid_hex_lowercase(self):
        self.assertTrue(is_valid_hex("deadbeef1234"))

    def test_valid_hex_uppercase(self):
        self.assertTrue(is_valid_hex("DEADBEEF1234"))

    def test_valid_hex_mixed_case(self):
        self.assertTrue(is_valid_hex("DeAdBeEf1234"))

    def test_valid_hex_single_char(self):
        self.assertTrue(is_valid_hex("0"))

    def test_invalid_hex_non_hex_chars(self):
        self.assertFalse(is_valid_hex("xyz123"))

    def test_invalid_hex_empty(self):
        self.assertFalse(is_valid_hex(""))

    def test_invalid_hex_special_chars(self):
        self.assertFalse(is_valid_hex("dead-beef"))

    def test_invalid_hex_spaces(self):
        self.assertFalse(is_valid_hex("dead beef"))

    def test_validate_tx_hex_valid(self):
        validate_transaction_hex("deadbeef")  # Should not raise

    def test_validate_tx_hex_empty(self):
        with self.assertRaises(ValueError):
            validate_transaction_hex("")

    def test_validate_tx_hex_odd_length(self):
        with self.assertRaises(ValueError):
            validate_transaction_hex("abc")

    def test_validate_tx_hex_invalid_chars(self):
        with self.assertRaises(ValueError):
            validate_transaction_hex("zzzz")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

class TestChunkTransaction(unittest.TestCase):

    def test_single_chunk_short_tx(self):
        result = chunk_transaction("a" * 100, 170)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "a" * 100)

    def test_exact_boundary(self):
        result = chunk_transaction("b" * 170, 170)
        self.assertEqual(len(result), 1)

    def test_multi_chunk(self):
        result = chunk_transaction("c" * 450, 170)
        # 450 hex chars / 170 = 3 chunks (170, 170, 110)
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]), 170)
        self.assertEqual(len(result[1]), 170)
        self.assertEqual(len(result[2]), 110)

    def test_reassembly_matches_original(self):
        original = "deadbeef" * 50
        chunks = chunk_transaction(original, 170)
        reassembled = "".join(chunks)
        self.assertEqual(reassembled, original)

    def test_empty_raises_error(self):
        with self.assertRaises(ValueError):
            chunk_transaction("", 170)

    def test_zero_chunk_size_raises(self):
        with self.assertRaises(ValueError):
            chunk_transaction("abcd", 0)

    def test_negative_chunk_size_raises(self):
        with self.assertRaises(ValueError):
            chunk_transaction("abcd", -1)

    def test_default_chunk_size(self):
        result = chunk_transaction("a" * 340)
        # 340 hex chars with default chunk size of 170 should be exactly 2 chunks
        self.assertEqual(len(result), 2)
        self.assertEqual(len(result[0]), 170)
        self.assertEqual(len(result[1]), 170)

    def test_chunk_size_one(self):
        result = chunk_transaction("abcd", 1)
        self.assertEqual(result, ["a", "b", "c", "d"])


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------


class TestGenerateSessionId(unittest.TestCase):

    def test_length(self):
        sid = generate_session_id()
        self.assertEqual(len(sid), 5)

    def test_is_hex(self):
        sid = generate_session_id()
        int(sid, 16)  # Should not raise

    def test_uniqueness(self):
        ids = {generate_session_id() for _ in range(100)}
        self.assertEqual(len(ids), 100) # Expecting all unique


class TestCreateSession(unittest.TestCase):

    def test_chunks_correct_count(self):
        session = create_session("aa" * 250, chunk_size=170)
        # 500 hex chars / 170 = 3 chunks (170, 170, 160)
        self.assertEqual(session.total_chunks, 3)

    def test_chunks_correct_count_default_size(self):
        session = create_session("aa" * 340)  # default chunk size is 170
        # # 680 hex chars / 170 = 4 chunks (170, 170, 170, 170)
        self.assertEqual(session.total_chunks, 4)

    def test_generates_id(self):
        session = create_session("aabbccdd")
        self.assertEqual(len(session.session_id), 5)

    def test_generates_id_is_hex(self):
        session = create_session("ffbb11dd")
        int(session.session_id, 16)  # Should not raise

    def test_invalid_hex_raises(self):
        with self.assertRaises(ValueError):
            create_session("not-hex-data")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            create_session("")

    def test_odd_length_raises(self):
        with self.assertRaises(ValueError):
            create_session("abc")

    def test_chunks_reassemble_to_original(self):
        original = "deadbeef" * 30
        session = create_session(original, chunk_size=170)
        reassembled = "".join(session.chunks)
        self.assertEqual(reassembled, original)


class TestGetChunkMessage(unittest.TestCase):

    def test_first_chunk(self):
        session = TransactionSession("abc12", ["chunk0", "chunk1", "chunk2"])
        msg = get_chunk_message(session, 0)
        self.assertEqual(msg.session_id, "abc12")
        self.assertEqual(msg.chunk_number, 1)  # 1-indexed
        self.assertEqual(msg.total_chunks, 3)
        self.assertEqual(msg.payload, "chunk0")

    def test_last_chunk(self):
        session = TransactionSession("abc12", ["chunk0", "chunk1"])
        msg = get_chunk_message(session, 1)
        self.assertEqual(msg.chunk_number, 2)
        self.assertEqual(msg.payload, "chunk1")

    def test_index_out_of_range(self):
        session = TransactionSession("abc12", ["chunk0"])
        with self.assertRaises(IndexError):
            get_chunk_message(session, 1)

    def test_negative_index(self):
        session = TransactionSession("abc12", ["chunk0"])
        with self.assertRaises(IndexError):
            get_chunk_message(session, -1)

    def test_format_output(self):
        session = TransactionSession("abc12", ["deadbeef"])
        msg = get_chunk_message(session, 0)
        self.assertEqual(msg.format(), "BTC_TX|abc12|1/1|deadbeef")


# ---------------------------------------------------------------------------
# Parsing: BTC_TX
# ---------------------------------------------------------------------------


class TestParseChunk(unittest.TestCase):

    def test_valid(self):
        msg = parse_chunk("BTC_TX|abc12|2/5|deadbeef")
        self.assertIsInstance(msg, ChunkMessage)
        self.assertEqual(msg.session_id, "abc12")
        self.assertEqual(msg.chunk_number, 2)
        self.assertEqual(msg.total_chunks, 5)
        self.assertEqual(msg.payload, "deadbeef")

    def test_wrong_prefix(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_CHUNK|abc12|1/3|data")

    def test_missing_parts(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|1/3")

    def test_too_many_parts(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|1/3|data|extra")

    def test_chunk_zero(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|0/3|data")

    def test_chunk_exceeds_total(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|4/3|data")

    def test_total_chunks_zero(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|1/0|data")

    def test_empty_session_id(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX||1/3|data")

    def test_non_numeric_chunk(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|x/3|data")
    
    def test_non_numeric_total(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|1/y|data")

    def test_empty_payload(self):
        with self.assertRaises(ValueError):
            parse_chunk("BTC_TX|abc12|1/1|")


# ---------------------------------------------------------------------------
# Parsing: BTC_CHUNK_ACK
# ---------------------------------------------------------------------------


class TestParseChunkAck(unittest.TestCase):

    def test_request_next(self):
        msg = parse_chunk_ack("BTC_CHUNK_ACK|abc12|1|OK|REQUEST_CHUNK|2")
        self.assertIsInstance(msg, ChunkAckMessage)
        self.assertEqual(msg.session_id, "abc12")
        self.assertEqual(msg.chunk_number, 1)
        self.assertEqual(msg.status, "OK")
        self.assertEqual(msg.request_next_chunk, 2)
        self.assertFalse(msg.all_received)

    def test_all_received(self):
        msg = parse_chunk_ack("BTC_CHUNK_ACK|def456|3|OK|ALL_CHUNKS_RECEIVED")
        self.assertIsInstance(msg, ChunkAckMessage)
        self.assertEqual(msg.session_id, "def456")
        self.assertEqual(msg.chunk_number, 3)
        self.assertEqual(msg.status, "OK")
        self.assertTrue(msg.all_received)
        self.assertIsNone(msg.request_next_chunk)

    def test_invalid_prefix(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("NOT_AN_ACK|abc12|1|OK")

    def test_missing_parts(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("BTC_CHUNK_ACK|abc12")

    def test_non_numeric_chunk(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("BTC_CHUNK_ACK|abc12|x|OK|REQUEST_CHUNK|2")
    
    def test_missing_request_next_number(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("BTC_CHUNK_ACK|abc12|1|OK|REQUEST_CHUNK")

    def test_unexpected_extra_parts(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("BTC_CHUNK_ACK|abc12|1|OK|EXTRA|unexpected")
    
    def test_non_numeric_request_next(self):
        with self.assertRaises(ValueError):
            parse_chunk_ack("BTC_CHUNK_ACK|abc12|1|OK|REQUEST_CHUNK|x")
    

if __name__ == "__main__":
    unittest.main()
