"""TransactionSender: Pure, reusable orchestration for chunked transaction sending.

This module extracts the stop-and-wait ARQ protocol from btcmesh_cli.py
into a reusable class that works with any BaseTransport implementation.
Pure code: no print, no logging, no file I/O (except via transport).
"""
from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Set, Callable

from core.protocol import create_session, get_chunk_message, parse_message, validate_transaction_hex
from core.message_types import ChunkAckMessage, AckMessage, NackMessage
from transport.base import BaseTransport


# ---------------------------------------------------------------------------
# Phase 1: Data Structures
# ---------------------------------------------------------------------------


@dataclass
class SendResult:
    """Return value from send_transaction().

    Either success=True with txid, or success=False with error message.
    """
    success: bool
    session_id: str
    txid: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        """Validate that success/txid/error are consistent."""
        if self.success and not self.txid:
            raise ValueError("success=True requires txid to be set")
        if not self.success and not self.error:
            raise ValueError("success=False requires error to be set")


class SendSession:
    """Internal state tracker for a transaction being sent.

    Tracks which chunks have been sent, which have been ACKed, retry counts,
    and timestamps for timeout detection. Not exposed to callers.
    """

    def __init__(self, session_id: str, total_chunks: int):
        """Initialize send session state.

        Args:
            session_id: Protocol session ID from create_session()
            total_chunks: Total number of chunks in transaction
        """
        self.session_id = session_id
        self.total_chunks = total_chunks
        self.chunks_sent = set()  # type: Set[int]
        self.chunks_acked = set()  # type: Set[int]
        self.retry_counts = {}  # type: Dict[int, int]
        self.sent_timestamps = {}  # type: Dict[int, float]
        self.current_chunk_index = 0  # 1-indexed
        self.all_chunks_received = False
        self.final_txid = None  # type: Optional[str]
        self.error = None  # type: Optional[str]
        self.failed = False
        # Threading: event set when we get a response, cleared at start of wait
        self._response_events = {}  # type: Dict[int, threading.Event]
        self._final_ack_event = threading.Event()

    def mark_chunk_sent(self, chunk_num: int) -> None:
        """Record that a chunk was sent."""
        self.chunks_sent.add(chunk_num)
        self.sent_timestamps[chunk_num] = time.time()
        if chunk_num not in self._response_events:
            self._response_events[chunk_num] = threading.Event()

    def mark_chunk_acked(self, chunk_num: int) -> None:
        """Record that a chunk ACK was received."""
        self.chunks_acked.add(chunk_num)
        if chunk_num in self._response_events:
            self._response_events[chunk_num].set()

    def get_response_event(self, chunk_num: int) -> threading.Event:
        """Get the event to wait on for a chunk ACK."""
        if chunk_num not in self._response_events:
            self._response_events[chunk_num] = threading.Event()
        return self._response_events[chunk_num]

    def clear_response_event(self, chunk_num: int) -> None:
        """Clear the event before waiting (for reuse)."""
        if chunk_num in self._response_events:
            self._response_events[chunk_num].clear()

    def increment_retry(self, chunk_num: int) -> None:
        """Track retry attempts for a chunk."""
        self.retry_counts[chunk_num] = self.retry_counts.get(chunk_num, 0) + 1

    def needs_resend(self, chunk_num: int, timeout_seconds: int) -> bool:
        """Check if a chunk should be resent (timeout)."""
        if chunk_num not in self.sent_timestamps:
            return False
        elapsed = time.time() - self.sent_timestamps[chunk_num]
        return elapsed > timeout_seconds

    def is_complete(self) -> bool:
        """Check if all chunks were ACKed."""
        return len(self.chunks_acked) == self.total_chunks

    def get_final_ack_event(self) -> threading.Event:
        """Get event to wait for final BTC_ACK."""
        return self._final_ack_event

    def signal_final_ack(self) -> None:
        """Signal that final ACK arrived."""
        self._final_ack_event.set()

    def clear_final_ack_event(self) -> None:
        """Clear final ACK event for waiting."""
        self._final_ack_event.clear()


# ---------------------------------------------------------------------------
# Phase 2: TransactionSender Core
# ---------------------------------------------------------------------------


class TransactionSender:
    """Orchestrates stop-and-wait ARQ sending of chunked transactions.

    Uses BaseTransport to send chunks and receive ACKs. Implements retry logic,
    timeout handling, and message routing. Supports concurrent sends via
    session isolation.

    Pure code: no print, no logging, no file I/O (except via transport).
    """

    def __init__(
        self,
        transport: BaseTransport,
        timeout_seconds: int = 30,
        max_retries: int = 3,
    ):
        """Initialize sender with transport and configuration.

        Args:
            transport: BaseTransport instance for sending/receiving
            timeout_seconds: Seconds to wait for each ACK (default 30)
            max_retries: Max retries per chunk (default 3)

        Raises:
            ValueError: If timeout_seconds or max_retries are invalid
        """
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.sessions = {}  # type: Dict[str, SendSession]
        self._on_response_received = None  # type: Optional[Callable[[str], None]]
        self._setup_message_handler()

    def _setup_message_handler(self) -> None:
        """Register callback with transport for incoming messages."""
        handler = lambda msg, sender_id: self._on_message(msg, sender_id)
        self.transport.set_message_handler(handler)

    def send_transaction(
        self,
        tx_hex: str,
        destination: str,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_chunk_sending: Optional[Callable[[int, int, int, str], None]] = None,
        on_response_received: Optional[Callable[[str], None]] = None,
    ) -> SendResult:
        """Send a transaction using stop-and-wait ARQ.

        Validates hex, chunks it, sends each chunk with ACK wait and retries,
        then waits for final BTC_ACK with TXID.

        Args:
            tx_hex: Raw transaction hex to send
            destination: Meshtastic node ID (e.g., "!deadbeef")
            on_progress: Optional callback(chunk_num, total_chunks) after each ACK
            on_chunk_sending: Optional callback(chunk_num, total, attempt, wire_format)
                called just before each send attempt (including retries)
            on_response_received: Optional callback(message_text) called for each
                incoming ACK/NACK wire message belonging to this session

        Returns:
            SendResult with success=True/txid or success=False/error

        Raises:
            ValueError: If tx_hex is invalid
            RuntimeError: If transport error occurs
        """
        # Validate input
        try:
            validate_transaction_hex(tx_hex)
        except ValueError as e:
            return SendResult(
                success=False,
                session_id="",
                error=str(e),
            )

        # Create protocol session (does chunking)
        try:
            protocol_session = create_session(tx_hex)
        except ValueError as e:
            return SendResult(
                success=False,
                session_id="",
                error=f"Failed to create session: {e}",
            )

        session_id = protocol_session.session_id
        send_session = SendSession(session_id, protocol_session.total_chunks)
        self.sessions[session_id] = send_session

        self._on_response_received = on_response_received
        try:
            # Do the sending (blocking)
            self._send_all_chunks(
                protocol_session,
                send_session,
                destination,
                on_progress,
                on_chunk_sending,
            )
            # Build and return result
            return self._build_result(send_session)
        finally:
            # Cleanup
            self._on_response_received = None
            self._cleanup_session(session_id)

    def _send_all_chunks(
        self,
        protocol_session,
        send_session: SendSession,
        destination: str,
        on_progress: Optional[Callable[[int, int], None]],
        on_chunk_sending: Optional[Callable[[int, int, int, str], None]],
    ) -> None:
        """Implement stop-and-wait sender: send all chunks with ACK waits.

        Updates send_session.error and send_session.failed on error.
        """
        total = send_session.total_chunks

        # Send each chunk with retry loop
        for chunk_index in range(total):
            # Check if session was failed by NACK
            if send_session.failed:
                return

            chunk_num = chunk_index + 1
            max_attempts = self.max_retries + 1  # +1 for initial attempt

            while max_attempts > 0:
                # Check if session was failed by NACK
                if send_session.failed:
                    return

                try:
                    # Clear event BEFORE sending (clear any stale signal)
                    send_session.clear_response_event(chunk_num)

                    # Get and send chunk
                    chunk_msg = get_chunk_message(protocol_session, chunk_index)
                    wire_format = chunk_msg.format()
                    attempt = send_session.retry_counts.get(chunk_num, 0) + 1
                    if on_chunk_sending:
                        on_chunk_sending(chunk_num, total, attempt, wire_format)
                    self.transport.send(wire_format, destination)
                    send_session.mark_chunk_sent(chunk_num)

                    # Wait for ACK with timeout
                    if self._wait_for_chunk_ack(send_session, chunk_num):
                        # Check if NACK set failed during wait
                        if send_session.failed:
                            return
                        # Got ACK, move to next chunk
                        if on_progress:
                            on_progress(chunk_num, total)
                        break
                    else:
                        # Timeout, retry
                        max_attempts -= 1
                        send_session.increment_retry(chunk_num)
                        if max_attempts == 0:
                            send_session.error = f"Chunk {chunk_num}: timeout after {self.max_retries} retries"
                            send_session.failed = True
                            return

                except Exception as e:
                    send_session.error = f"Chunk {chunk_num}: {str(e)}"
                    send_session.failed = True
                    return

        # All chunks sent, wait for final BTC_ACK
        if not self._wait_for_final_ack(send_session):
            # Check if NACK set failed during final ACK wait
            if not send_session.failed:
                send_session.error = "No final ACK from relay"
                send_session.failed = True

    def _wait_for_chunk_ack(self, send_session: SendSession, chunk_num: int) -> bool:
        """Block waiting for chunk ACK with timeout.

        Returns:
            True if ACK received, False if timeout
        """
        event = send_session.get_response_event(chunk_num)
        return event.wait(timeout=self.timeout_seconds)

    def _wait_for_final_ack(self, send_session: SendSession) -> bool:
        """Block waiting for final BTC_ACK with timeout.

        Returns:
            True if ACK received, False if timeout
        """
        event = send_session.get_final_ack_event()
        send_session.clear_final_ack_event()
        # Wait with 2x timeout for final ACK (gives server time to process all chunks)
        return event.wait(timeout=self.timeout_seconds * 2)

    def _on_message(self, message_text: str, sender_id: str) -> None:
        """Handle incoming message from transport.

        Routes to appropriate handler based on message type.
        Must handle parse errors gracefully (ignore malformed messages).
        """
        try:
            msg = parse_message(message_text)
        except (ValueError, AttributeError):
            # Malformed message, ignore
            return

        # Find session
        session = self.sessions.get(msg.session_id)
        if session is None:
            # Message for unknown session, ignore
            return

        # Notify observer before routing
        if self._on_response_received:
            self._on_response_received(message_text)

        # Route by message type
        if isinstance(msg, ChunkAckMessage):
            self._handle_chunk_ack(session, msg)
        elif isinstance(msg, AckMessage):
            self._handle_final_ack(session, msg)
        elif isinstance(msg, NackMessage):
            self._handle_nack(session, msg)

    def _handle_chunk_ack(self, session: SendSession, msg: ChunkAckMessage) -> None:
        """Handle BTC_CHUNK_ACK message."""
        session.mark_chunk_acked(msg.chunk_number)

    def _handle_final_ack(self, session: SendSession, msg: AckMessage) -> None:
        """Handle BTC_ACK success message."""
        session.final_txid = msg.txid
        session.signal_final_ack()

    def _handle_nack(self, session: SendSession, msg: NackMessage) -> None:
        """Handle BTC_NACK error message.

        Mark session as failed and signal all waiting threads immediately
        to unblock them without waiting for timeouts.
        """
        session.error = msg.error_detail
        session.failed = True
        # Signal ALL chunk response events to unblock any waiting chunk ACK waits
        for chunk_num in range(1, session.total_chunks + 1):
            event = session.get_response_event(chunk_num)
            event.set()
        # Also signal final ACK event
        session.signal_final_ack()


# ---------------------------------------------------------------------------
# Phase 3: Result Compilation
# ---------------------------------------------------------------------------


    def _build_result(self, send_session: SendSession) -> SendResult:
        """Build SendResult from completed send_session."""
        if not send_session.failed and send_session.final_txid:
            return SendResult(
                success=True,
                session_id=send_session.session_id,
                txid=send_session.final_txid,
            )
        else:
            return SendResult(
                success=False,
                session_id=send_session.session_id,
                error=send_session.error or "Unknown error",
            )

    def _cleanup_session(self, session_id: str) -> None:
        """Clean up session from tracking dict."""
        self.sessions.pop(session_id, None)
