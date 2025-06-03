#!/usr/bin/env python3
import argparse
import sys
import re

def is_valid_hex(s):
    try:
        int(s, 16)
        return True
    except Exception:
        return False

def main():
    parser = argparse.ArgumentParser(description="Send a raw Bitcoin transaction via Meshtastic LoRa relay.")
    parser.add_argument('-d', '--destination', required=True, help='Destination node ID (e.g., !abcdef12)')
    parser.add_argument('-tx', '--tx', required=True, help='Raw transaction hex string')
    parser.add_argument('--dry-run', action='store_true', help='Only parse and print arguments, do not send')
    args = parser.parse_args()

    # Validate tx hex
    tx_hex = args.tx
    if len(tx_hex) % 2 != 0 or not re.fullmatch(r'[0-9a-fA-F]+', tx_hex):
        print('Invalid raw transaction hex: must be even length and hex characters only.', file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"Arguments parsed successfully:")
        print(f"  Destination: {args.destination}")
        print(f"  Raw TX Hex: {args.tx}")
        sys.exit(0)

    # (Actual sending logic will be implemented in later stories)
    print("Sending not implemented yet.")
    sys.exit(0)

if __name__ == '__main__':
    main() 