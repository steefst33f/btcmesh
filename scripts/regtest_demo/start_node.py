#!/usr/bin/env python3
"""Start (or reuse) a local Bitcoin Core regtest node for demoing
btcmesh end-to-end, without needing real funds or a synced chain.

Idempotent: if a node is already answering RPC on the configured port,
this just prints its connection info and exits - safe to re-run.

On a fresh datadir, this also creates a wallet and mines 101 blocks
(the minimum for a coinbase output to mature) so there's spendable
balance to send from right away.

Usage:
    python scripts/regtest_demo/start_node.py

Configuration (all optional, via env vars - see _common.py):
    BTCMESH_REGTEST_DATADIR      default: ~/.btcmesh-regtest
    BTCMESH_REGTEST_RPC_USER     default: btcmesh
    BTCMESH_REGTEST_RPC_PASSWORD default: btcmeshdemo
    BTCMESH_REGTEST_RPC_PORT     default: 18443
    BTCMESH_REGTEST_WALLET       default: btcmesh-demo
    BITCOIND_BIN / BITCOIN_CLI_BIN   only needed if not on PATH
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import DATADIR, RPC_PASSWORD, RPC_PORT, RPC_USER, WALLET_NAME, cli, find_binary, is_node_running, rpc_summary

STARTUP_TIMEOUT_SECONDS = 20


def main():
    if is_node_running():
        print("Regtest node already running. RPC connection info for the GUI:")
        print(rpc_summary())
        return

    os.makedirs(DATADIR, exist_ok=True)
    bitcoind = find_binary("bitcoind")
    print(f"Starting bitcoind (regtest, datadir={DATADIR})...")
    subprocess.run(
        [
            bitcoind,
            "-regtest",
            f"-datadir={DATADIR}",
            f"-rpcuser={RPC_USER}",
            f"-rpcpassword={RPC_PASSWORD}",
            f"-rpcport={RPC_PORT}",
            "-daemon",
            "-fallbackfee=0.0001",
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
            f"check {DATADIR}/regtest/debug.log"
        )

    wallets = cli("listwallets")
    if WALLET_NAME not in wallets:
        loaded = cli("listwalletdir")
        already_on_disk = any(w["name"] == WALLET_NAME for w in loaded.get("wallets", []))
        if already_on_disk:
            print(f"Loading existing wallet '{WALLET_NAME}'...")
            cli("loadwallet", WALLET_NAME)
        else:
            print(f"Creating wallet '{WALLET_NAME}'...")
            cli("createwallet", WALLET_NAME)

    balance = cli("getbalance", wallet=True)
    if balance == 0:
        print("Wallet is empty - mining 101 blocks to fund it...")
        address = cli("getnewaddress", wallet=True)
        cli("generatetoaddress", 101, address, wallet=True)
        balance = cli("getbalance", wallet=True)

    print(f"\nRegtest node ready. Wallet '{WALLET_NAME}' balance: {balance} BTC")
    print("\nRPC connection info for the GUI (or CLI --port / .env):")
    print(rpc_summary())
    print(
        "\nNote: regtest doesn't mine new blocks on its own - a sent "
        "transaction will sit unconfirmed until one is mined (see "
        "start_mining.py), or run:\n"
        "  python scripts/regtest_demo/stop_node.py   # to shut down"
    )


if __name__ == "__main__":
    main()
