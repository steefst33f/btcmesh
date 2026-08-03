#!/usr/bin/env python3
"""Thin CLI entry point for running the BTCMesh relay server.

All business logic lives in server/receiver.py (chunk reassembly, RPC
broadcast) and transport/meshtastic_serial.py (device connection). This
file only handles: config loading, startup/shutdown, and logging.
"""
import argparse
import sys
import time

from core.config_loader import (
    get_meshtastic_serial_port,
    load_app_config,
    load_bitcoin_rpc_config,
    load_reassembly_timeout,
)
from core.device_watchdog import build_device_watchdog
from core.logger_setup import server_logger
from core.reassembler import TransactionReassembler
from core.rpc_client import BitcoinRPCClient
from core.transaction_history import TransactionHistory
from server.receiver import TransactionReceiver, ChunkReceived, BroadcastResult
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError

CHECK_TIMEOUTS_INTERVAL_SECONDS = 10


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the BTCMesh relay server."
    )
    parser.add_argument(
        "-p", "--port",
        help="Meshtastic serial port to use (e.g. /dev/ttyUSB0). "
             "Overrides MESHTASTIC_SERIAL_PORT in .env. If neither is set, "
             "auto-detects - which fails or picks unpredictably if more than "
             "one device is connected.",
    )
    return parser.parse_args(argv)


def build_receiver(transport, rpc_client, reassembly_timeout, history, watchdog) -> TransactionReceiver:
    """Wire TransactionReceiver's callbacks to server_logger + history - the
    same callback set and log wording btcmesh_server_gui.py's Activity Log
    uses, just logged instead of pushed to a GUI queue. Also wires
    record_success()/record_failure() into watchdog (Story 26.5)."""

    def on_chunk_received(evt: ChunkReceived):
        server_logger.info(f"[{evt.session_id}] Received chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}")
        if evt.chunk_num < evt.total_chunks:
            server_logger.info(f"[{evt.session_id}] Requesting chunk {evt.chunk_num + 1}/{evt.total_chunks}...")
        else:
            server_logger.info(f"[{evt.session_id}] All {evt.total_chunks} chunks received. Reassembly successful.")
        # Only reached once the ack for this chunk has already been sent
        # successfully - a correct "this device is genuinely working" signal.
        watchdog.record_success()

    def on_broadcast_started(session_id, sender_id):
        server_logger.info(f"[{session_id}] Broadcasting transaction to Bitcoin network...")

    def on_broadcast(result: BroadcastResult):
        if result.success:
            server_logger.info(f"[{result.session_id}] Broadcast success. TXID: {result.txid}")
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="success", txid=result.txid, raw_tx=result.raw_tx)
        else:
            server_logger.error(f"[{result.session_id}] Broadcast failed: {result.error}")
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="failed", error=result.error, raw_tx=result.raw_tx)

    def on_error(session_id, sender_id, error):
        server_logger.warning(f"[{session_id}] Error from {sender_id}: {error}")
        history.add(session_id=session_id, sender=sender_id, status="failed", error=error, raw_tx=None)

    def on_wire_sent(message_text):
        server_logger.info(f"  -> {message_text}")

    def on_wire_received(message_text):
        server_logger.info(f"  <- {message_text}")

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
    )


def run_server(port=None) -> int:
    """Connect, run until Ctrl+C, then disconnect. Returns process exit code."""
    server_logger.info("Loading configuration...")
    load_app_config()

    resolved_port = port or get_meshtastic_serial_port()
    server_logger.info(f"Connecting to Meshtastic device{f' ({resolved_port})' if resolved_port else ' (auto-detect)'}...")
    transport = MeshtasticSerialTransport()
    try:
        transport.connect(resolved_port)
    except TransportConnectionError as e:
        server_logger.error(f"Failed to connect to Meshtastic device: {e}")
        return 2
    server_logger.info(f"Connected to Meshtastic device. Node ID: {transport.local_node_id}")

    # Match old behavior: a failed RPC connection does not stop the server -
    # Meshtastic keeps receiving/reassembling/ACKing chunks, only the eventual
    # broadcast step fails once a transaction actually completes.
    try:
        rpc_client = BitcoinRPCClient(load_bitcoin_rpc_config())
        server_logger.info(f"Connected to Bitcoin Core RPC node. Chain: {rpc_client.chain}")
    except Exception as e:
        rpc_client = None
        server_logger.error(f"Failed to connect to Bitcoin Core RPC node: {e}. Continuing without RPC connection.")

    watchdog, power_control = build_device_watchdog(
        transport,
        on_recovery_attempt=lambda: server_logger.warning(
            "Device appears wedged - attempting automatic recovery..."
        ),
        on_recovered=lambda outcome: server_logger.info(
            f"Device recovered. Reconnected at {outcome.new_device_path}."
        ),
        on_recovery_failed=lambda outcome: server_logger.error(
            f"Automatic device recovery failed: {outcome.error}"
        ),
    )
    if power_control:
        server_logger.info("Automatic device-recovery enabled via relay.")
    else:
        server_logger.info(
            "RELAY_SERIAL_PORT not configured - automatic device-wedge "
            "recovery is disabled (wedge detection still logs, but won't "
            "recover on its own)."
        )

    reassembly_timeout, _source = load_reassembly_timeout()
    history = TransactionHistory()
    receiver = build_receiver(transport, rpc_client, reassembly_timeout, history, watchdog)

    server_logger.info("Server started. Listening for incoming transactions... (Ctrl+C to stop)")
    try:
        last_cleanup = time.time()
        while True:
            now = time.time()
            if now - last_cleanup >= CHECK_TIMEOUTS_INTERVAL_SECONDS:
                receiver.check_timeouts()
                last_cleanup = now
            watchdog.tick(now)
            time.sleep(1)
    except KeyboardInterrupt:
        server_logger.info("Server shutting down by user request (Ctrl+C).")
    finally:
        transport.disconnect()
    return 0


def main():
    args = parse_args()
    sys.exit(run_server(args.port))


if __name__ == "__main__":
    main()
