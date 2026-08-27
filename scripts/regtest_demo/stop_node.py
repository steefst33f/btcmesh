#!/usr/bin/env python3
"""Stop the local Bitcoin Core regtest demo node started by
start_node.py. Safe to run even if it's not running (no-op).

Usage:
    python scripts/regtest_demo/stop_node.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import cli, is_node_running


def main():
    if not is_node_running():
        print("Regtest node isn't running - nothing to do.")
        return

    print("Stopping regtest node...")
    cli("stop")
    print("Stop requested (bitcoind shuts down in the background).")


if __name__ == "__main__":
    main()
