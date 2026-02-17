"""Dataclass definitions for BTCMesh protocol message types.

Each wire message type has a format() method that produces the exact
wire-format string sent over Meshtastic. See project/protocol_spec.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.constants import (
    CHUNK_DELIMITER,
    CHUNK_INDEX_DELIMITER,
    MSG_BTC_TX,
    MSG_CHUNK_ACK,
    MSG_ACK,
    MSG_NACK,
    ACK_REQUEST_CHUNK,
    ACK_ALL_RECEIVED,
    TXID_PREFIX,
)


@dataclass
class ChunkMessage:
    """A BTC_TX chunk message (client -> server)."""

    session_id: str
    chunk_number: int  # 1-indexed
    total_chunks: int
    payload: str  # hex payload fragment

    def format(self) -> str:
        D, I = CHUNK_DELIMITER, CHUNK_INDEX_DELIMITER
        return f"{MSG_BTC_TX}{D}{self.session_id}{D}{self.chunk_number}{I}{self.total_chunks}{D}{self.payload}"


@dataclass
class ChunkAckMessage:
    """A BTC_CHUNK_ACK message (server -> client).

    Two variants:
    - request_next_chunk is set: server requests the next chunk
    - all_received is True: server has all chunks
    """

    session_id: str
    chunk_number: int
    request_next_chunk: Optional[int] = None
    all_received: bool = False

    def format(self) -> str:
        D = CHUNK_DELIMITER
        base = f"{MSG_CHUNK_ACK}{D}{self.session_id}{D}{self.chunk_number}"
        if self.all_received:
            return f"{base}{D}{ACK_ALL_RECEIVED}"
        if self.request_next_chunk is not None:
            return f"{base}{D}{ACK_REQUEST_CHUNK}{D}{self.request_next_chunk}"
        return base


@dataclass
class AckMessage:
    """A BTC_ACK success message (server -> client)."""

    session_id: str
    txid: str

    def format(self) -> str:
        D = CHUNK_DELIMITER
        return f"{MSG_ACK}{D}{self.session_id}{D}{TXID_PREFIX}{self.txid}"


@dataclass
class NackMessage:
    """A BTC_NACK error message (server -> client)."""

    session_id: str
    error_detail: str

    def format(self) -> str:
        D = CHUNK_DELIMITER
        return f"{MSG_NACK}{D}{self.session_id}{D}{self.error_detail}"


@dataclass
class TransactionSession:
    """Represents a chunked transaction ready for sending.

    Not a wire message type — used internally to hold a session's
    ID and pre-computed chunk list.
    """

    session_id: str
    chunks: List[str]

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)
