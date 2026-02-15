"""Pure protocol functions for the BTCMesh chunked transaction relay.

All functions in this module are pure — no print, no logging, no I/O.
They raise ValueError for invalid inputs. See project/protocol_spec.md.
"""
from __future__ import annotations

import uuid
from typing import Union

from core.constants import (
    DEFAULT_CHUNK_SIZE,
    SESSION_ID_LENGTH,
    CHUNK_DELIMITER,
    CHUNK_INDEX_DELIMITER,
    MSG_BTC_TX,
    MSG_CHUNK_ACK,
    MSG_ACK,
    MSG_NACK,
    ACK_REQUEST_CHUNK,
    ACK_ALL_RECEIVED,
    STATUS_SUCCESS,
    STATUS_ERROR,
    TXID_PREFIX,
)
from core.message_types import (
    ChunkMessage,
    ChunkAckMessage,
    AckMessage,
    NackMessage,
    TransactionSession,
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def is_valid_hex(s: str) -> bool:
    """Check if a string is a valid hexadecimal string.

    Returns True if s is a non-empty string of hex characters, False otherwise.
    """
    if not s:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def validate_transaction_hex(tx_hex: str) -> None:
    """Validate a raw transaction hex string.

    Raises:
        ValueError: If tx_hex is empty, odd-length, or contains non-hex characters.
    """
    if not tx_hex:
        raise ValueError("Transaction hex cannot be empty")
    if len(tx_hex) % 2 != 0:
        raise ValueError("Transaction hex must have even length")
    if not is_valid_hex(tx_hex):
        raise ValueError("Transaction hex contains invalid characters")


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def chunk_transaction(
    tx_hex: str, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> list[str]:
    """Split a hex string into chunks of specified size.

    Args:
        tx_hex: Hex string to split.
        chunk_size: Maximum characters per chunk (default: 170).

    Returns:
        List of hex string chunks.

    Raises:
        ValueError: If tx_hex is empty or chunk_size <= 0.
    """
    if not tx_hex:
        raise ValueError("Transaction hex cannot be empty")
    if chunk_size <= 0:
        raise ValueError("Chunk size must be positive")
    return [tx_hex[i : i + chunk_size] for i in range(0, len(tx_hex), chunk_size)]


# ---------------------------------------------------------------------------
# Session ID generation
# ---------------------------------------------------------------------------


def generate_session_id() -> str:
    """Generate a unique 5-character hex session ID."""
    return uuid.uuid4().hex[:SESSION_ID_LENGTH]


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------


def create_session(
    tx_hex: str, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> TransactionSession:
    """Create a new transaction session with chunked data.

    Validates the transaction hex, generates a session ID, and splits
    the hex into chunks.

    Raises:
        ValueError: If tx_hex is invalid.
    """
    validate_transaction_hex(tx_hex)
    chunks = chunk_transaction(tx_hex, chunk_size)
    return TransactionSession(
        session_id=generate_session_id(),
        chunks=chunks,
    )


def get_chunk_message(
    session: TransactionSession, chunk_index: int
) -> ChunkMessage:
    """Get a ChunkMessage for a specific chunk in a session.

    Args:
        session: The transaction session.
        chunk_index: 0-based index of the chunk.

    Returns:
        ChunkMessage with 1-indexed chunk_number.

    Raises:
        IndexError: If chunk_index is out of range.
    """
    if chunk_index < 0 or chunk_index >= session.total_chunks:
        raise IndexError(
            f"Chunk index {chunk_index} out of range (0-{session.total_chunks - 1})"
        )
    return ChunkMessage(
        session_id=session.session_id,
        chunk_number=chunk_index + 1,
        total_chunks=session.total_chunks,
        payload=session.chunks[chunk_index],
    )


# ---------------------------------------------------------------------------
# Message parsing
# ---------------------------------------------------------------------------


def parse_chunk(message: str) -> ChunkMessage:
    """Parse a BTC_TX chunk message.

    Expected format: BTC_TX|<session_id>|<chunk_num>/<total_chunks>|<payload>

    Raises:
        ValueError: If format is invalid.
    """
    parts = message.split(CHUNK_DELIMITER)
    if len(parts) != 4 or parts[0] != MSG_BTC_TX:
        raise ValueError(f"Invalid BTC_TX format: {message}")
    session_id = parts[1]
    if not session_id:
        raise ValueError("Empty session_id in BTC_TX message")
    try:
        chunk_num_str, total_str = parts[2].split(CHUNK_INDEX_DELIMITER)
        chunk_number = int(chunk_num_str)
        total_chunks = int(total_str)
    except ValueError:
        raise ValueError(f"Invalid chunk numbering in BTC_TX: {parts[2]}")
    if not (0 < chunk_number <= total_chunks and total_chunks > 0):
        raise ValueError(f"Invalid chunk numbers: {chunk_number}/{total_chunks}")
    return ChunkMessage(
        session_id=session_id,
        chunk_number=chunk_number,
        total_chunks=total_chunks,
        payload=parts[3],
    )


def parse_chunk_ack(message: str) -> ChunkAckMessage:
    """Parse a BTC_CHUNK_ACK message.

    Expected formats:
        BTC_CHUNK_ACK|<session>|<chunk>|OK|REQUEST_CHUNK|<next>
        BTC_CHUNK_ACK|<session>|<chunk>|OK|ALL_CHUNKS_RECEIVED

    Raises:
        ValueError: If format is invalid.
    """
    parts = message.split(CHUNK_DELIMITER)
    if len(parts) < 4 or parts[0] != MSG_CHUNK_ACK:
        raise ValueError(f"Invalid BTC_CHUNK_ACK format: {message}")
    session_id = parts[1]
    try:
        chunk_number = int(parts[2])
    except ValueError:
        raise ValueError(f"Invalid chunk number in ACK: {parts[2]}")
    status = parts[3]

    request_next_chunk = None
    all_received = False

    if len(parts) >= 5:
        if parts[4] == ACK_ALL_RECEIVED:
            all_received = True
        elif parts[4] == ACK_REQUEST_CHUNK and len(parts) >= 6:
            try:
                request_next_chunk = int(parts[5])
            except ValueError:
                raise ValueError(f"Invalid next chunk in ACK: {parts[5]}")

    return ChunkAckMessage(
        session_id=session_id,
        chunk_number=chunk_number,
        status=status,
        request_next_chunk=request_next_chunk,
        all_received=all_received,
    )


def parse_ack(message: str) -> AckMessage:
    """Parse a BTC_ACK success message.

    Expected format: BTC_ACK|<session>|SUCCESS|TXID:<txid>

    Raises:
        ValueError: If format is invalid.
    """
    parts = message.split(CHUNK_DELIMITER)
    if len(parts) < 4 or parts[0] != MSG_ACK:
        raise ValueError(f"Invalid BTC_ACK format: {message}")
    if parts[2] != STATUS_SUCCESS:
        raise ValueError(f"BTC_ACK with non-SUCCESS status: {parts[2]}")
    txid_part = parts[3]
    if not txid_part.startswith(TXID_PREFIX):
        raise ValueError(f"Missing TXID: prefix in BTC_ACK: {txid_part}")
    txid = txid_part[len(TXID_PREFIX) :]
    return AckMessage(session_id=parts[1], txid=txid)


def parse_nack(message: str) -> NackMessage:
    """Parse a BTC_NACK error message.

    Expected format: BTC_NACK|<session>|ERROR|<details>
    Note: error_detail may contain '|' characters, so we split with maxsplit=3.

    Raises:
        ValueError: If format is invalid.
    """
    parts = message.split(CHUNK_DELIMITER, 3)
    if len(parts) < 4 or parts[0] != MSG_NACK:
        raise ValueError(f"Invalid BTC_NACK format: {message}")
    if parts[2] != STATUS_ERROR:
        raise ValueError(f"BTC_NACK with non-ERROR status: {parts[2]}")
    return NackMessage(session_id=parts[1], error_detail=parts[3])


# ---------------------------------------------------------------------------
# Unified message dispatcher
# ---------------------------------------------------------------------------

ParsedMessage = Union[ChunkMessage, ChunkAckMessage, AckMessage, NackMessage]

_PARSERS = {
    MSG_BTC_TX: parse_chunk,
    MSG_CHUNK_ACK: parse_chunk_ack,
    MSG_ACK: parse_ack,
    MSG_NACK: parse_nack,
}


def parse_message(message: str) -> ParsedMessage:
    """Parse any BTCMesh protocol message into its typed dataclass.

    Detects the message type from the prefix and delegates to the
    appropriate parser.

    Raises:
        ValueError: If the message type is unknown or the format is invalid.
    """
    msg_type = message.split(CHUNK_DELIMITER, 1)[0] if CHUNK_DELIMITER in message else message
    parser = _PARSERS.get(msg_type)
    if parser is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    return parser(message)
