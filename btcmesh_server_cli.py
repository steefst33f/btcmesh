#!/usr/bin/env python3
"""Thin CLI entry point for running the BTCMesh relay server.

All business logic lives in server/receiver.py (chunk reassembly, RPC
broadcast) and the transport/ implementations (device connection). This
file only handles: config loading, startup/shutdown, and logging.
"""
import argparse
import sys

from core.config_loader import (
    get_meshtastic_serial_port,
    load_app_config,
    load_bitcoin_rpc_config,
    load_log_level,
    load_reassembly_timeout,
)
from core.device_watchdog import build_device_watchdog
from core.logger_setup import server_logger, set_logger_level
from core.rpc_client import BitcoinRPCClient
from core.transaction_history import TransactionHistory
from server.run_loop import build_receiver, run_polling_loop
from transport.factory import get_transport, TRANSPORT_CHOICES, TRANSPORT_DISPLAY_NAMES
from transport.base import TransportConnectionError
from transport.power_control import probe_relay_board_id


def _log(message: str, level: int, highlight: bool = False) -> None:
    """Sink for server/run_loop.py's shared callbacks (Issue 34) - plain
    logging, `highlight` has no meaning for a text logger (it only affects
    the GUI's color-coding) so it's accepted and ignored."""
    server_logger.log(level, message)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the BTCMesh relay server."
    )
    parser.add_argument(
        "-p", "--port",
        help="Serial port to use (e.g. /dev/ttyUSB0). For --transport "
             "meshtastic, overrides MESHTASTIC_SERIAL_PORT in .env when set, "
             "otherwise auto-detects - which fails or picks unpredictably if "
             "more than one device is connected. For --transport meshcore, "
             "auto-detects only when exactly one serial port is present.",
    )
    parser.add_argument(
        "--transport", choices=TRANSPORT_CHOICES, default="meshtastic",
        help="Mesh transport to use (default: meshtastic).",
    )
    return parser.parse_args(argv)


def run_server(transport_name: str = "meshtastic", port=None) -> int:
    """Connect, run until Ctrl+C, then disconnect. Returns process exit code."""
    server_logger.info("Loading configuration...")
    load_app_config()
    log_level, _log_level_source = load_log_level()
    set_logger_level(server_logger, log_level)

    resolved_port = port
    if resolved_port is None and transport_name == "meshtastic":
        resolved_port = get_meshtastic_serial_port()
    display_name = TRANSPORT_DISPLAY_NAMES.get(transport_name, transport_name)

    # The relay board (Story 26.7) is Meshtastic-specific infrastructure -
    # this check has no MeshCore equivalent yet.
    if (
        transport_name == "meshtastic"
        and resolved_port
        and probe_relay_board_id(resolved_port)
    ):
        server_logger.error(
            f"{resolved_port} is the relay board's control port, not a "
            "Meshtastic device - select a different device."
        )
        return 2
    server_logger.info(f"Connecting to {display_name} device{f' ({resolved_port})' if resolved_port else ' (auto-detect)'}...")
    transport = get_transport(transport_name)
    try:
        if transport_name == "meshtastic":
            transport.connect(resolved_port, log_firmware_info=True)
        else:
            transport.connect(resolved_port)
    except TransportConnectionError as e:
        server_logger.error(f"Failed to connect to {display_name} device: {e}")
        return 2
    server_logger.info(f"Connected to {display_name} device. Node ID: {transport.local_node_id}")

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
        # "Configured", not "enabled" or "connected" - power_control is
        # built purely from RELAY_SERIAL_PORT being set in .env
        # (build_device_watchdog()), with no attempt to actually reach the
        # relay board. Whether it's really there and working is only found
        # out if/when a recovery is attempted (Issue 42).
        server_logger.info(
            "Automatic device-recovery configured via relay "
            "(RELAY_SERIAL_PORT set) - actual availability isn't "
            "confirmed until a recovery is attempted."
        )
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
    sys.exit(run_server(args.transport, args.port))


if __name__ == "__main__":
    main()
