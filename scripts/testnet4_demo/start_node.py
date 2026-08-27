#!/usr/bin/env python3
"""Start (or reuse) a real Bitcoin Core testnet4 node for demoing
btcmesh against the live public network - so a sent transaction shows
up on a real block explorer (mempool.space/testnet4) with the real
mempool.space UI, not a self-hosted look-alike.

Idempotent: if a node is already answering RPC on the configured port,
this just prints its connection info and exits - safe to re-run.

Unlike the regtest demo (scripts/regtest_demo/), this does NOT create
a wallet or mine blocks - testnet4 is a real network, not something a
local node controls. See the README in this directory for funding a
wallet via a faucet.

First run downloads the real testnet4 chain (~13GB+ and growing) - this
takes a while and needs internet access. Re-runs just reuse what's
already synced.

Usage:
    python scripts/testnet4_demo/start_node.py

Configuration (all optional, via env vars - see _common.py):
    BTCMESH_TESTNET4_DATADIR      default: /Volumes/Blockchain/btcmesh-testnet4
    BTCMESH_TESTNET4_RPC_USER     default: btcmesh
    BTCMESH_TESTNET4_RPC_PASSWORD default: btcmeshdemo
    BTCMESH_TESTNET4_RPC_PORT     default: 48332
    BITCOIND_BIN / BITCOIN_CLI_BIN   only needed if not on PATH
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATADIR, RPC_PASSWORD, RPC_PORT, RPC_USER, cli, find_binary, is_node_running, rpc_summary

STARTUP_TIMEOUT_SECONDS = 20


def main():
    if is_node_running():
        info = cli("getblockchaininfo")
        print("Testnet4 node already running.")
        _print_sync_status(info)
        print("\nRPC connection info for the GUI:")
        print(rpc_summary())
        return

    parent_dir = os.path.dirname(DATADIR.rstrip("/"))
    if parent_dir and not os.path.isdir(parent_dir):
        raise SystemExit(
            f"'{parent_dir}' doesn't exist - if this is meant to be an "
            "external disk, make sure it's mounted, or override the "
            "datadir with BTCMESH_TESTNET4_DATADIR=/some/other/path."
        )

    os.makedirs(DATADIR, exist_ok=True)
    bitcoind = find_binary("bitcoind")
    print(f"Starting bitcoind (testnet4, datadir={DATADIR})...")
    print("First run downloads the real chain - this can take a while.")
    subprocess.run(
        [
            bitcoind,
            "-testnet4",
            f"-datadir={DATADIR}",
            f"-rpcuser={RPC_USER}",
            f"-rpcpassword={RPC_PASSWORD}",
            f"-rpcport={RPC_PORT}",
            "-daemon",
        ],
        check=True,
    )

    print("Waiting for RPC to come up...")
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if is_node_running():
            break
        time.sleep(0.5)
    else:
        raise SystemExit(
            f"bitcoind didn't answer RPC within {STARTUP_TIMEOUT_SECONDS}s - "
            f"check {DATADIR}/testnet4/debug.log"
        )

    info = cli("getblockchaininfo")
    _print_sync_status(info)
    print("\nRPC connection info for the GUI:")
    print(rpc_summary())
    print(
        "\nStill syncing? Re-run this script anytime to check progress "
        "(it's idempotent - reuses the running node). Once "
        "initialblockdownload is false, sync is complete.\n"
        "  python scripts/testnet4_demo/stop_node.py   # to shut down"
    )


def _print_sync_status(info: dict) -> None:
    if info["initialblockdownload"]:
        pct = info["verificationprogress"] * 100
        print(f"Syncing: block {info['blocks']}/{info['headers']} ({pct:.1f}%)")
    else:
        print(f"Fully synced at block {info['blocks']}.")


if __name__ == "__main__":
    main()
