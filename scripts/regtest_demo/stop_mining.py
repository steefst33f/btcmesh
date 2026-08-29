#!/usr/bin/env python3
"""Stop the background mining loop started by start_mining.py. Safe to
run even if it's not running (no-op).

Usage:
    python scripts/regtest_demo/stop_mining.py
"""
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import PID_FILE


def main():
    if not os.path.exists(PID_FILE):
        print("Mining loop isn't running - nothing to do.")
        return

    with open(PID_FILE) as f:
        pid = f.read().strip()

    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"Stopped mining loop (PID {pid}).")
        except OSError:
            print(f"Mining loop (PID {pid}) was already gone.")

    os.remove(PID_FILE)


if __name__ == "__main__":
    main()
