#!/usr/bin/env python3
"""Start a background loop that mines one regtest block every N seconds,
so sent transactions actually confirm during a demo without manually
mining after each one. Runs detached - safe to leave running for the
whole demo session; stop it with stop_mining.py.

Usage:
    python scripts/regtest_demo/start_mining.py
    python scripts/regtest_demo/start_mining.py --interval 30
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATADIR, MINING_LOG_FILE, PID_FILE, cli, is_node_running

_INTERNAL_FLAG = "--_internal-loop-worker"


def _run_loop(interval: float) -> None:
    """The actual mining loop body - only reached in the detached child
    process (see main()), never in the foreground invocation."""
    address = cli("getnewaddress", wallet=True)
    print(f"Mining loop started: 1 block every {interval}s to {address}", flush=True)
    while True:
        time.sleep(interval)
        try:
            block_hash = cli("generatetoaddress", 1, address, wallet=True)[0]
            print(f"Mined block {block_hash}", flush=True)
        except Exception as e:
            print(f"generatetoaddress failed (node stopped?): {e}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--interval", type=float, default=15.0,
        help="Seconds between mined blocks (default: 15)",
    )
    parser.add_argument(_INTERNAL_FLAG, action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args._internal_loop_worker:
        _run_loop(args.interval)
        return

    if not is_node_running():
        raise SystemExit("Regtest node isn't running - run start_node.py first.")

    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            old_pid = f.read().strip()
        if old_pid and _pid_alive(int(old_pid)):
            raise SystemExit(
                f"Mining loop already running (PID {old_pid}). "
                "Run stop_mining.py first to change the interval."
            )

    os.makedirs(DATADIR, exist_ok=True)
    log = open(MINING_LOG_FILE, "a")
    proc = subprocess.Popen(
        [sys.executable, __file__, _INTERNAL_FLAG, "--interval", str(args.interval)],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))

    print(f"Mining loop started in background (PID {proc.pid}), 1 block every {args.interval}s.")
    print(f"Log: {MINING_LOG_FILE}")
    print("Stop with: python scripts/regtest_demo/stop_mining.py")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if __name__ == "__main__":
    main()
