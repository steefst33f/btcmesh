# Regtest Demo Node

Scripts for spinning up a throwaway local Bitcoin Core regtest node so
btcmesh can be demoed end-to-end - a real transaction actually gets
broadcast and confirmed - without needing real funds, a synced chain,
or internet access.

Regtest is a private network fully controlled by its own node: blocks
are mined on demand, coins have no real value, and everything resets if
the datadir is wiped. This is the standard way to demo/test Bitcoin
software.

## Requirements

`bitcoind` and `bitcoin-cli` (Bitcoin Core) on `PATH`. For a from-source
build that hasn't been installed, either add the build's `bin/` dir to
`PATH`, or set `BITCOIND_BIN`/`BITCOIN_CLI_BIN` to the full binary paths
(see `_common.py`).

## Usage

```bash
python scripts/regtest_demo/start_node.py
```

First run: starts `bitcoind -regtest`, creates a wallet, and mines 101
blocks (the minimum for a coinbase output to mature) so there's 50 BTC
of spendable balance right away. Re-running it just reuses the existing
node/wallet - safe to call anytime, including at the start of every demo
session.

It prints the RPC connection info to paste into the GUI's Bitcoin RPC
fields (or a CLI `--port` flag / `.env` - see the main README):

```
Host:     127.0.0.1
Port:     18443
User:     btcmesh
Password: btcmeshdemo
```

To shut it down:

```bash
python scripts/regtest_demo/stop_node.py
```

### Keeping transactions confirming automatically

Regtest doesn't mine blocks on its own - a transaction sent during the
demo sits unconfirmed until a block is mined. Either mine one by hand:

```bash
python -c "
import sys; sys.path.insert(0, 'scripts/regtest_demo')
from _common import cli
cli('generatetoaddress', 1, cli('getnewaddress', wallet=True), wallet=True)
"
```

or run the background mining loop for the whole demo:

```bash
python scripts/regtest_demo/start_mining.py             # 1 block/15s (default)
python scripts/regtest_demo/start_mining.py --interval 30
python scripts/regtest_demo/stop_mining.py
```

`start_mining.py` runs detached (survives the launching terminal
closing) and logs to `~/.btcmesh-regtest/mining_loop.log`.

## Configuration

All optional, via environment variables (defaults shown):

| Variable | Default |
|---|---|
| `BTCMESH_REGTEST_DATADIR` | `~/.btcmesh-regtest` |
| `BTCMESH_REGTEST_RPC_USER` | `btcmesh` |
| `BTCMESH_REGTEST_RPC_PASSWORD` | `btcmeshdemo` |
| `BTCMESH_REGTEST_RPC_PORT` | `18443` |
| `BTCMESH_REGTEST_WALLET` | `btcmesh-demo` |

## Using Electrum to generate addresses

Yes, with a caveat: Electrum can generate valid regtest addresses
completely **offline**, with no server connection at all - address
derivation is pure local math from the wallet's seed/xpub. That covers
"an address to use as the demo's send destination," which is almost
certainly all that's needed here.

```bash
electrum --regtest
```

Create/restore a wallet as normal, then use the **Receive** tab to
generate addresses on the go. The wallet doesn't need to be synced or
even connected to this regtest node for this to work.

What Electrum **can't** do without more setup: show a live balance or
transaction history for that wallet, or broadcast from within Electrum
itself. Electrum wallets talk the Electrum protocol, not Bitcoin Core's
RPC directly - that needs a separate Electrum-protocol server (e.g.
`electrs` or `Fulcrum`) indexing this regtest node, which is a heavier
piece of infrastructure to stand up and isn't included here. Worth
setting up separately if the demo ever needs that (e.g. showing "yes,
the funds landed" inside Electrum itself, not just via `bitcoin-cli`) -
not needed just to generate addresses.
