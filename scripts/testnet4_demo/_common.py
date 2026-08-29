"""Shared constants and bitcoin-cli/bitcoind wrappers for the testnet4
demo scripts in this directory. Not a public API - just avoids repeating
the same subprocess plumbing across start_node.py/stop_node.py.
"""
import json
import os
import shutil
import subprocess

# Defaults match this project's actual demo setup (2026-08-26): a real
# testnet4 chain is ~13GB and growing, kept off the internal disk on
# purpose - see the README's "Why an external disk" section. Override
# BTCMESH_TESTNET4_DATADIR if no external volume of that name exists,
# or a different location is preferred.
DATADIR = os.environ.get("BTCMESH_TESTNET4_DATADIR", "/Volumes/Blockchain/btcmesh-testnet4")
RPC_USER = os.environ.get("BTCMESH_TESTNET4_RPC_USER", "btcmesh")
RPC_PASSWORD = os.environ.get("BTCMESH_TESTNET4_RPC_PASSWORD", "btcmeshdemo")
RPC_PORT = int(os.environ.get("BTCMESH_TESTNET4_RPC_PORT", "48332"))  # testnet4's Core default


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


def cli(*args, check: bool = True):
    """Run bitcoin-cli with the shared testnet4 datadir/RPC credentials.
    Returns parsed JSON if the output looks like JSON, otherwise the raw
    stdout string. Raises CalledProcessError on failure unless check=False
    (in which case the CompletedProcess is returned so the caller can
    inspect returncode/stderr itself - e.g. to detect "not running")."""
    cmd = [
        find_binary("bitcoin-cli"),
        "-testnet4",
        f"-datadir={DATADIR}",
        f"-rpcuser={RPC_USER}",
        f"-rpcpassword={RPC_PASSWORD}",
        f"-rpcport={RPC_PORT}",
    ]
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
