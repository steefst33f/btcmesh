#!/usr/bin/env python3
"""Stop the testnet4 demo node started by start_node.py. Safe to run
even if it's not running (no-op).

Usage:
    python scripts/testnet4_demo/stop_node.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import cli, is_node_running


def main():
    if not is_node_running():
        print("Testnet4 node isn't running - nothing to do.")
        return

    print("Stopping testnet4 node...")
    cli("stop")
    print("Stop requested (bitcoind shuts down in the background).")


if __name__ == "__main__":
    main()
