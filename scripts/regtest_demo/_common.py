"""Shared constants and bitcoin-cli/bitcoind wrappers for the regtest demo
scripts in this directory. Not a public API - just avoids repeating the
same subprocess plumbing across start_node.py/stop_node.py/
start_mining.py/stop_mining.py.
"""
import json
import os
import shutil
import subprocess

DATADIR = os.environ.get("BTCMESH_REGTEST_DATADIR", os.path.expanduser("~/.btcmesh-regtest"))
RPC_USER = os.environ.get("BTCMESH_REGTEST_RPC_USER", "btcmesh")
RPC_PASSWORD = os.environ.get("BTCMESH_REGTEST_RPC_PASSWORD", "btcmeshdemo")
RPC_PORT = int(os.environ.get("BTCMESH_REGTEST_RPC_PORT", "18443"))
WALLET_NAME = os.environ.get("BTCMESH_REGTEST_WALLET", "btcmesh-demo")

PID_FILE = os.path.join(DATADIR, "mining_loop.pid")
MINING_LOG_FILE = os.path.join(DATADIR, "mining_loop.log")


def find_binary(name: str) -> str:
    """Locate bitcoind/bitcoin-cli on PATH, or raise a clear error.

    Override via the BITCOIND_BIN/BITCOIN_CLI_BIN env vars if the binary
    isn't on PATH (e.g. a from-source build that hasn't been installed).
    """
    env_var = "BITCOIND_BIN" if name == "bitcoind" else "BITCOIN_CLI_BIN"
    override = os.environ.get(env_var)
    if override:
        return override
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit(
        f"Could not find '{name}' on PATH. Either add it to PATH, or set "
        f"{env_var}=/path/to/{name} (e.g. in the shell profile)."
    )


def cli(*args, wallet: bool = False, check: bool = True):
    """Run bitcoin-cli with the shared regtest datadir/RPC credentials.
    Returns parsed JSON if the output looks like JSON, otherwise the raw
    stdout string. Raises CalledProcessError on failure unless check=False
    (in which case the CompletedProcess is returned so the caller can
    inspect returncode/stderr itself - e.g. to detect "not running")."""
    cmd = [
        find_binary("bitcoin-cli"),
        "-regtest",
        f"-datadir={DATADIR}",
        f"-rpcuser={RPC_USER}",
        f"-rpcpassword={RPC_PASSWORD}",
        f"-rpcport={RPC_PORT}",
    ]
    if wallet:
        cmd.append(f"-rpcwallet={WALLET_NAME}")
    cmd.extend(str(a) for a in args)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    if not check:
        return result

    out = result.stdout.strip()
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return out


def is_node_running() -> bool:
    result = cli("getblockchaininfo", check=False)
    return result.returncode == 0


def rpc_summary() -> str:
    return (
        f"  Host:     127.0.0.1\n"
        f"  Port:     {RPC_PORT}\n"
        f"  User:     {RPC_USER}\n"
        f"  Password: {RPC_PASSWORD}"
    )
