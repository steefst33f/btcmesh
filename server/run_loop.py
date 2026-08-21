"""Shared server orchestration (Issue 34).

TransactionReceiver's callback wiring and the check_timeouts/liveness/
watchdog polling loop, used identically by btcmesh_server_cli.py and
btcmesh_server_gui.py. Previously copy-pasted between the two, with only
the logging sink (server_logger vs. a GUI result queue) differing.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional, Protocol

from core.reassembler import TransactionReassembler
from core.transaction_history import TransactionHistory
from server.receiver import BroadcastResult, ChunkReceived, TransactionReceiver

CHECK_TIMEOUTS_INTERVAL_SECONDS = 10
LIVENESS_LOG_INTERVAL_SECONDS = 300
# Issue 21: an operator checking the log later has no way to tell the
# server was actually still running vs. silently dead/hung, unless some
# other activity happened to log something. A periodic positive signal
# closes that gap regardless of whether anything else is happening.


class LogFn(Protocol):
    """Sink signature for build_receiver()/run_polling_loop(). A plain
    Callable[..., None] can't express `highlight`'s default, so this is
    a Protocol instead - the real, checkable contract, not just a comment.

    highlight marks a message for visual emphasis (the GUI colors these
    distinctly from plain wire traffic/status lines); a plain logger
    sink ignores it.
    """
    def __call__(self, message: str, level: int, highlight: bool = False) -> None: ...


def build_receiver(
    transport,
    rpc_client,
    reassembly_timeout: int,
    history: TransactionHistory,
    watchdog,
    log: LogFn,
) -> TransactionReceiver:
    """Wire TransactionReceiver's callbacks to `log` + `history` - the
    same callback set and log wording every UI entrypoint uses, just
    routed through whatever sink that UI provides. Also wires
    record_success()/record_failure() into watchdog (Story 26.5) via
    on_transport_success/on_transport_error, symmetric with each other -
    every successful/failed reply send counts, not just chunk-acks
    (Story 28.3 review fix; see project/plans/story_28_3.md)."""

    def on_chunk_received(evt: ChunkReceived):
        log(f"[{evt.session_id}] Received chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}",
            logging.INFO, highlight=True)
        if evt.chunk_num < evt.total_chunks:
            log(f"[{evt.session_id}] Requesting chunk {evt.chunk_num + 1}/{evt.total_chunks}...",
                logging.INFO, highlight=True)
        else:
            log(f"[{evt.session_id}] All {evt.total_chunks} chunks received. Reassembly successful.",
                logging.INFO, highlight=True)

    def on_broadcast_started(session_id, sender_id):
        log(f"[{session_id}] Broadcasting transaction to Bitcoin network...", logging.INFO, highlight=True)

    def on_broadcast(result: BroadcastResult):
        if result.success:
            log(f"[{result.session_id}] Broadcast success. TXID: {result.txid}", logging.INFO)
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="success", txid=result.txid, raw_tx=result.raw_tx)
        else:
            log(f"[{result.session_id}] Broadcast failed: {result.error}", logging.ERROR)
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="failed", error=result.error, raw_tx=result.raw_tx)

    def on_error(session_id, sender_id, error):
        log(f"[{session_id}] Error from {sender_id}: {error}", logging.WARNING)
        history.add(session_id=session_id, sender=sender_id, status="failed", error=error, raw_tx=None)

    def on_wire_sent(message_text):
        log(f"  -> {message_text}", logging.INFO)

    def on_wire_received(message_text):
        log(f"  <- {message_text}", logging.INFO)

    return TransactionReceiver(
        transport, rpc_client,
        reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
        on_chunk_received=on_chunk_received,
        on_broadcast_started=on_broadcast_started,
        on_broadcast=on_broadcast,
        on_error=on_error,
        on_wire_sent=on_wire_sent,
        on_wire_received=on_wire_received,
        on_transport_error=lambda e: watchdog.record_failure(),
        on_transport_success=lambda: watchdog.record_success(),
    )


def run_polling_loop(
    receiver: TransactionReceiver,
    watchdog,
    log: LogFn,
    stop_check: Callable[[], bool] = lambda: False,
    on_tick: Optional[Callable[[List], None]] = None,
) -> None:
    """Drive the receiver's periodic maintenance once per second until
    stop_check() returns True: check_timeouts() every
    CHECK_TIMEOUTS_INTERVAL_SECONDS, a liveness log every
    LIVENESS_LOG_INTERVAL_SECONDS, and watchdog.tick() every second.

    TransactionReceiver itself is purely reactive - incoming chunks are
    handled the instant the transport's pubsub callback fires, with no
    polling needed for that part (see Story 23.1). This loop only drives
    the maintenance that has to happen on a schedule instead.

    on_tick, if given, is called every iteration with the current
    active-sessions snapshot - used by the GUI to keep its "Active
    Sessions" panel live. The CLI has no such display and omits it, which
    also avoids an extra get_active_sessions() call every second it
    never needed.
    """
    last_cleanup = time.time()
    last_liveness_log = time.time()
    while not stop_check():
        now = time.time()
        if on_tick:
            on_tick(receiver.get_active_sessions())
        if now - last_cleanup >= CHECK_TIMEOUTS_INTERVAL_SECONDS:
            receiver.check_timeouts()
            last_cleanup = now
        if now - last_liveness_log >= LIVENESS_LOG_INTERVAL_SECONDS:
            active = len(receiver.get_active_sessions())
            log(f"Server heartbeat: alive, listening. {active} active session(s).", logging.INFO)
            last_liveness_log = now
        watchdog.tick(now)
        time.sleep(1)
