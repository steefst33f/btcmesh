"""TransactionReceiver: reusable server-side orchestration for receiving,
reassembling, and broadcasting chunked Bitcoin transactions.

Extracted from btcmesh_server.py's on_receive_text_message()/
send_meshtastic_reply()/main() loop. Pure aside from the injected
transport/rpc_client: no direct Meshtastic or Bitcoin RPC library imports,
no print, no logging, no file I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from core.reassembler import (
    CHUNK_PARTS_DELIMITER,
    CHUNK_PREFIX,
    InvalidChunkFormatError,
    MismatchedTotalChunksError,
    ReassemblyError,
    TransactionReassembler,
)
from core.rpc_client import BitcoinRPCClient
from transport.base import BaseTransport

_MAX_NACK_LEN = 200

# Concise error-message mapping for common Bitcoin Core RPC rejection
# reasons, kept short enough to fit LoRa payload constraints in a NACK.
_CONCISE_ERROR_MAP = (
    ("Transaction outputs already in utxo set", "TX already in UTXO set"),
    ("Transaction already in block chain", "TX already in chain"),
    ("insufficient fee", "Insufficient fee"),
    ("missing inputs", "Missing inputs"),
    ("bad-txns-inputs-spent", "Inputs spent"),
    ("bad-txns-in-belowout", "Input < Output"),
    ("too-long-mempool-chain", "Chain too long"),
    ("mempool full", "Mempool full"),
    ("replacement transaction", "RBF disabled"),
    ("non-mandatory-script-verify-flag", "Script verify failed"),
    ("transaction already abandoned", "TX abandoned"),
    ("bad-txns-nonstandard-inputs", "Non-std inputs"),
    ("bad-txns-oversize", "TX too large"),
    ("dust", "Dust output"),
    ("fee is too high", "Fee too high"),
    ("absurdly-high-fee", "Absurd fee"),
)


def _concise_error_message(error: str) -> str:
    """Map a verbose Bitcoin Core RPC error to a short NACK-friendly string."""
    lowered = error.lower()
    for needle, short in _CONCISE_ERROR_MAP:
        if needle.lower() in lowered:
            return short
    if "version" in lowered and "reject" in lowered:
        return "Version rejected"
    return error


@dataclass
class ChunkReceived:
    """A single valid chunk was received, reassembled-into, and ACKed."""
    session_id: str
    sender_id: str
    chunk_num: int
    total_chunks: int


@dataclass
class BroadcastResult:
    """Result of a completed reassembly + RPC broadcast attempt."""
    session_id: str
    sender_id: str
    success: bool
    txid: Optional[str] = None
    error: Optional[str] = None
    raw_tx: Optional[str] = None


class TransactionReceiver:
    """Orchestrates receiving, reassembling, and broadcasting transactions.

    Registers itself as the transport's message handler on construction.
    Callers must periodically invoke check_timeouts() (e.g. from a GUI's
    Clock or a CLI's own loop) to NACK stale reassembly sessions - this
    class does not run its own background thread.
    """

    def __init__(
        self,
        transport: BaseTransport,
        rpc_client: BitcoinRPCClient,
        reassembler: Optional[TransactionReassembler] = None,
        on_chunk_received: Optional[Callable[[ChunkReceived], None]] = None,
        on_broadcast: Optional[Callable[[BroadcastResult], None]] = None,
        on_error: Optional[Callable[[str, str, str], None]] = None,
        # on_error(session_id, sender_id, error_message) - fires for
        # reassembly errors, unexpected processing errors, AND stale-session
        # timeouts (all are just "this session failed with error X" from a
        # caller's perspective).
        on_wire_sent: Optional[Callable[[str], None]] = None,
        on_wire_received: Optional[Callable[[str], None]] = None,
        # on_wire_sent/on_wire_received(message_text) - fire for the raw
        # wire-format text of every outgoing reply (CHUNK_ACK/ACK/NACK) and
        # incoming chunk message, mirroring client/sender.py's
        # on_chunk_sending/on_response_received. Purely for callers that want
        # to display the raw protocol traffic (e.g. a GUI activity log) -
        # the semantic callbacks above already cover everything needed for
        # business logic.
        on_broadcast_started: Optional[Callable[[str, str], None]] = None,
        # on_broadcast_started(session_id, sender_id) - fires right before the
        # RPC broadcast call, once reassembly has already succeeded. Separate
        # from on_broadcast (which only fires once the RPC call returns) so a
        # caller can show a distinct "broadcasting..." step for the RPC
        # round-trip, which can take a noticeable moment (e.g. over Tor).
    ):
        self.transport = transport
        self.rpc_client = rpc_client
        self.reassembler = reassembler or TransactionReassembler()
        self._on_chunk_received = on_chunk_received
        self._on_broadcast = on_broadcast
        self._on_error = on_error
        self._on_wire_sent = on_wire_sent
        self._on_wire_received = on_wire_received
        self._on_broadcast_started = on_broadcast_started
        self.transport.set_message_handler(self._on_message)

    def _send(self, message: str, sender_id: str) -> None:
        """Send a reply and report its raw wire text via on_wire_sent."""
        self.transport.send(message, sender_id)
        if self._on_wire_sent:
            self._on_wire_sent(message)

    def _on_message(self, message_text: str, sender_id: str) -> None:
        if not message_text.startswith(CHUNK_PREFIX):
            return

        if self._on_wire_received:
            self._on_wire_received(message_text)

        # Best-effort pre-parse, only to get chunk_num/total_chunks for the
        # ACK reply below. reassembler.add_chunk() (called in the try block
        # below) is the actual authority on format validity - if this parse
        # fails, leave the defaults and let add_chunk() raise the properly
        # categorized error instead of masking it with a parse error here.
        session_id = "UNKNOWN"
        chunk_num, total_chunks = 1, 1
        try:
            parts = message_text[len(CHUNK_PREFIX):].split(CHUNK_PARTS_DELIMITER)
            session_id = parts[0] if parts and parts[0] else "UNKNOWN"
            chunk_info = parts[1] if len(parts) > 1 else ""
            if "/" in chunk_info:
                chunk_num_s, total_s = chunk_info.split("/")
                chunk_num, total_chunks = int(chunk_num_s), int(total_s)
        except Exception:
            pass

        try:
            reassembled_hex = self.reassembler.add_chunk(sender_id, message_text)

            if chunk_num < total_chunks:
                ack = f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|REQUEST_CHUNK|{chunk_num + 1}"
            else:
                ack = f"BTC_CHUNK_ACK|{session_id}|{chunk_num}|ALL_CHUNKS_RECEIVED"
            self._send(ack, sender_id)

            if self._on_chunk_received:
                self._on_chunk_received(
                    ChunkReceived(session_id, sender_id, chunk_num, total_chunks)
                )

            if reassembled_hex:
                self._broadcast(session_id, sender_id, reassembled_hex)

        except (InvalidChunkFormatError, MismatchedTotalChunksError) as e:
            error_type = type(e).__name__.replace("Error", "").replace("Invalid", "Invalid ")
            detail = f"{error_type}: {e}"
            self._send_nack(session_id, sender_id, detail)
            if self._on_error:
                self._on_error(session_id, sender_id, detail)
        except ReassemblyError as e:
            if self._on_error:
                self._on_error(session_id, sender_id, str(e))
        except Exception as e:
            if self._on_error:
                self._on_error(session_id, sender_id, str(e))

    def _broadcast(self, session_id: str, sender_id: str, raw_tx: str) -> None:
        if self._on_broadcast_started:
            self._on_broadcast_started(session_id, sender_id)
        txid, error = self.rpc_client.broadcast_transaction(raw_tx)
        if txid:
            self._send(f"BTC_ACK|{session_id}|TXID:{txid}", sender_id)
            if self._on_broadcast:
                self._on_broadcast(
                    BroadcastResult(session_id, sender_id, True, txid=txid, raw_tx=raw_tx)
                )
        else:
            concise_error = _concise_error_message(str(error))
            self._send_nack(session_id, sender_id, concise_error)
            if self._on_broadcast:
                self._on_broadcast(
                    BroadcastResult(session_id, sender_id, False, error=str(error), raw_tx=raw_tx)
                )

    def _send_nack(self, session_id: str, sender_id: str, detail: str) -> None:
        msg = f"BTC_NACK|{session_id}|{detail}"
        if len(msg) > _MAX_NACK_LEN:
            msg = msg[: _MAX_NACK_LEN - 3] + "..."
        self._send(msg, sender_id)

    def check_timeouts(self) -> None:
        """Check for and NACK stale reassembly sessions. Call periodically."""
        for session_info in self.reassembler.cleanup_stale_sessions():
            self._send_nack(
                session_info["tx_session_id"],
                session_info["sender_id_str"],
                session_info["error_message"],
            )
            if self._on_error:
                self._on_error(
                    session_info["tx_session_id"],
                    session_info["sender_id_str"],
                    session_info["error_message"],
                )

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """Active reassembly sessions, for UI display."""
        return self.reassembler.get_active_sessions_info()