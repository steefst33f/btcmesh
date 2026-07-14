#!/usr/bin/env python3
"""Thin CLI entry point for sending a Bitcoin transaction via Meshtastic relay.

All business logic lives in client/sender.py (chunking, ARQ, retries) and
transport/meshtastic_serial.py (device connection). This file only handles:
argument parsing, output formatting, and exit codes.
"""
import argparse
import sys
import os

from core.config_loader import get_meshtastic_serial_port
from core.logger_setup import setup_logger
from core.protocol import validate_transaction_hex
from client.sender import TransactionSender, create_preview
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError

CLI_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logs", "btcmesh_client_cli.log"
)
cli_logger = setup_logger("btcmesh_client_cli", CLI_LOG_FILE)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Send a raw Bitcoin transaction via Meshtastic LoRa relay."
    )
    parser.add_argument(
        "-d", "--destination", required=True,
        help="Destination node ID (e.g., !abcdef12)",
    )
    parser.add_argument(
        "-tx", "--tx", required=True, help="Raw transaction hex string"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only show the chunking preview, do not send",
    )
    parser.add_argument(
        "-p", "--port",
        help="Meshtastic serial port to use (e.g. /dev/ttyUSB0). "
             "Overrides MESHTASTIC_SERIAL_PORT in .env. If neither is set, "
             "auto-detects - which fails or picks unpredictably if more than "
             "one device is connected.",
    )
    return parser.parse_args(argv)


def run_preview(tx_hex: str) -> int:
    """Show how the transaction would be chunked, without sending."""
    preview = create_preview(tx_hex)
    print(f"Preview: {preview.total_chunks} chunk(s)")
    for chunk in preview.chunks:
        print(chunk.wire_format)
    return 0


def run_send(destination: str, tx_hex: str, port: str = None) -> int:
    """Connect to the Meshtastic device and send the transaction."""
    resolved_port = port or get_meshtastic_serial_port()
    print(f"Connecting to Meshtastic device ({resolved_port or 'auto-detect'})...")

    transport = MeshtasticSerialTransport()
    try:
        transport.connect(resolved_port)
    except TransportConnectionError as e:
        print(f"Failed to connect to Meshtastic device: {e}", file=sys.stderr)
        cli_logger.error(f"Failed to connect: {e}")
        return 2

    try:
        sender = TransactionSender(transport)

        def on_chunk_sending(chunk_num, total, attempt, wire_format):
            if attempt > 1:
                print(f"Retrying chunk {chunk_num}/{total} (retry {attempt - 1})...")
            else:
                print(f"Sending chunk {chunk_num}/{total}...")
            cli_logger.info(f"Sending chunk {chunk_num}/{total} (attempt {attempt}): {wire_format}")

        def on_progress(chunk_num, total):
            print(f"Received ACK for chunk {chunk_num}/{total}")
            cli_logger.info(f"ACK for chunk {chunk_num}/{total}")

        def on_response_received(message_text):
            cli_logger.debug(f"Received: {message_text}")

        result = sender.send_transaction(
            tx_hex, destination,
            on_progress=on_progress,
            on_chunk_sending=on_chunk_sending,
            on_response_received=on_response_received,
        )
    finally:
        transport.disconnect()

    if result.success:
        print(f"Transaction successfully broadcast by relay. TXID: {result.txid}")
        cli_logger.info(f"Success: TXID {result.txid}")
        return 0

    print(f"Transaction failed: {result.error}", file=sys.stderr)
    cli_logger.error(f"Failed: {result.error}")
    return 1


def cli_main(argv=None) -> int:
    """Thin CLI orchestration. Returns process exit code."""
    args = parse_args(argv)

    try:
        validate_transaction_hex(args.tx)
    except ValueError as e:
        print(f"Invalid raw transaction hex: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        return run_preview(args.tx)
    return run_send(args.destination, args.tx, args.port)


def main():
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
