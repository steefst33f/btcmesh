# Testnet4 Demo Setup

A demo setup that shows btcmesh working against the real Bitcoin
testnet4 network - a signed transaction sent over LoRa mesh gets
broadcast for real and shows up on the actual mempool.space explorer.

Compare with `scripts/regtest_demo/`, which is instant and free but
self-contained (nothing to show a "live network" feel, and its explorer
is a lightweight look-alike, not the real mempool.space UI). Testnet4
suits a demo where the audience benefits from "this is a real public
network"; regtest suits fast iteration during development.

## Why an external disk

A real testnet4 chain is several GB and growing - kept off the internal
disk on purpose in this setup. `start_node.py` defaults its datadir to
`/Volumes/Blockchain/btcmesh-testnet4` (an external volume); override
with `BTCMESH_TESTNET4_DATADIR=/some/other/path` if no external volume
of that name exists, or a different location is preferred (internal
disk works fine too).

## 1. Start the node

```bash
python scripts/testnet4_demo/start_node.py
```

First run downloads the real chain - this takes a while (expect it to
run in the background for a good chunk of time; re-run the script
anytime to check progress, it's idempotent). Once
`initialblockdownload` is `false`, sync is complete.

RPC connection info for the GUI (or CLI `--port` / `.env`):

```
Host:     127.0.0.1
Port:     48332
User:     btcmesh
Password: btcmeshdemo
```

To shut it down:

```bash
python scripts/testnet4_demo/stop_node.py
```

## 2. Two Electrum wallets

Two independent wallets are needed: one to send from, one to receive
into. Electrum (`brew install --cask electrum` if not already
installed) supports running multiple instances as long as each points
at a different wallet file:

```bash
electrum --testnet4 -w ~/.btcmesh-testnet4/electrum-wallets/sender
electrum --testnet4 -w ~/.btcmesh-testnet4/electrum-wallets/receiver
```

**`--testnet4` matters** - Electrum's `--testnet` flag defaults to
testnet3, a different network from the testnet4 node set up above.
Using the wrong one means addresses/balances won't line up with
anything the node knows about.

For each wallet's setup wizard:
- **Standard wallet** (not multi-sig, not watch-only/import - signing
  transactions requires actual keys)
- **Create a new seed**
- **Use proxy?** No - not needed for this
- **Select Electrum server?** Yes, pick Autoconnect (or any server in
  the list). This isn't optional: Electrum needs *some* Electrum-
  protocol server to see the wallet's balance/UTXOs and build a
  transaction - address generation alone works offline, but
  constructing a spend doesn't.

### Why not point Electrum at the node started above?

`bitcoind` doesn't speak the Electrum wire protocol - only JSON-RPC
(what btcmesh itself uses). A truly self-hosted Electrum server needs
an indexer like `electrs` or `Fulcrum` sitting in between, which is
extra setup (install it, let it index the node, point Electrum at it).
For a demo wallet holding worthless testnet coins, a public server is
the pragmatic choice - there's no real privacy stake here. Worth
revisiting only if "fully self-hosted, no third party sees anything"
matters for the demo itself.

## 3. Fund the sender wallet

Get its receiving address from the **Receive** tab, then request
testnet4 coins from a faucet:

- https://mempool.space/testnet4/faucet
- https://coinfaucet.eu/en/btc-testnet4/
- https://testnet.help/en/btcfaucet/testnet
- https://bitcoinfaucet.uo1.net/

Faucet availability/rate-limits change - if one doesn't work, try
another.

### The "missing-inputs" gotcha

A fresh faucet deposit is usually **unconfirmed** for a while (testnet4
averages ~10 min/block). Until it confirms, the local node doesn't know
about it yet, and any transaction spending it will fail
`sendrawtransaction`/`testmempoolaccept` with `bad-txns-inputs-missing
orspent` / `missing-inputs` - not a bug, just the deposit not existing
in the node's view of the chain yet. Two ways to check for this ahead
of time:

```bash
# Check confirmation status on the public network:
curl -s "https://mempool.space/testnet4/api/tx/<txid>/status"

# Check what the local node thinks (safe, doesn't broadcast):
bitcoin-cli -testnet4 -datadir=<DATADIR> -rpcuser=btcmesh -rpcpassword=btcmeshdemo \
    testmempoolaccept '["<raw tx hex>"]'
```

If it's still unconfirmed, either wait for a block, or run the
mesh-send anyway to test the transport/reassembly path (that part
works regardless of confirmation status; only the final broadcast step
fails until confirmation).

## 4. Build the transaction, without broadcasting it

In the **sender** Electrum wallet's **Send** tab: paste the receiver
wallet's address (from its own Receive tab), enter an amount, then use
**Preview** (not the button that broadcasts immediately) - this signs
the transaction and opens a details dialog with an export/copy option
for the raw hex. That hex is what goes into the btcmesh client GUI's
"Paste raw transaction hex here..." field - the client doesn't take
addresses, it relays an already-signed transaction exactly as-is.

## 5. Send it over the mesh, verify it landed

Run the send from the client GUI as normal. Once the server side
broadcasts successfully, check:

- `https://mempool.space/testnet4/tx/<txid>` - shows unconfirmed in the
  mempool, then confirmed once mined.
- The receiver Electrum wallet's balance, once confirmed.

## Sanity-checking a raw hex before sending it over the mesh

Cheaper to catch a problem before a multi-chunk LoRa transmission than
after:

```bash
bitcoin-cli -testnet4 -datadir=<DATADIR> -rpcuser=btcmesh -rpcpassword=btcmeshdemo \
    decoderawtransaction "<raw tx hex>"
```
