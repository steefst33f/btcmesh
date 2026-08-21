#!/usr/bin/env python3
"""Thin CLI entry point for running the BTCMesh relay server.

All business logic lives in server/receiver.py (chunk reassembly, RPC
broadcast) and transport/meshtastic_serial.py (device connection). This
file only handles: config loading, startup/shutdown, and logging.
"""
import argparse
import sys

from core.config_loader import (
    get_meshtastic_serial_port,
    load_app_config,
    load_bitcoin_rpc_config,
    load_reassembly_timeout,
)
from core.device_watchdog import build_device_watchdog
from core.logger_setup import server_logger
from core.rpc_client import BitcoinRPCClient
from core.transaction_history import TransactionHistory
from server.run_loop import build_receiver, run_polling_loop
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError


def _log(message: str, level: int, primary: bool = False) -> None:
    """Sink for server/run_loop.py's shared callbacks (Issue 34) - plain
    logging, `primary` has no meaning for a text logger (it only affects
    the GUI's color-coding) so it's accepted and ignored."""
    server_logger.log(level, message)


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
    receiver = build_receiver(transport, rpc_client, reassembly_timeout, history, watchdog, log=_log)

    server_logger.info("Server started. Listening for incoming transactions... (Ctrl+C to stop)")
    try:
        run_polling_loop(receiver, watchdog, log=_log)
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
