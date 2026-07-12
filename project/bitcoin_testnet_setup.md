# Bitcoin Testnet Node Setup for BTC Mesh Relay

This guide covers installing and running a Bitcoin Core node on testnet3, and
wiring it up as the RPC backend for `btcmesh_server.py` / `btcmesh_server_gui.py`.

## 1. Install Bitcoin Core

Download a prebuilt release from [bitcoincore.org](https://bitcoincore.org/en/download/)
or build from source. Either way, you end up with `bitcoind`, `bitcoin-cli`, and
optionally `bitcoin-qt` on your `PATH` (or reachable by full path).

Verify it's available:

```bash
bitcoind --version
bitcoin-cli --version
```

## 2. Locate (or create) `bitcoin.conf`

Default data directories:

- **macOS**: `~/Library/Application Support/Bitcoin/bitcoin.conf`
- **Linux**: `~/.bitcoin/bitcoin.conf`
- **Windows**: `%APPDATA%\Bitcoin\bitcoin.conf`

If you're not sure whether one already exists (e.g. from a prior setup),
search for it:

```bash
find ~ -maxdepth 6 -iname "bitcoin.conf" 2>/dev/null
```

Also check whether `bitcoind`/`bitcoin-qt` is normally launched with an explicit
`-datadir=` or `-conf=` argument (e.g. in a shell alias or script) — that would
point at a non-default conf file instead.

A minimal `bitcoin.conf` for testnet3 + RPC access from btcmesh:

```ini
testnet=1
server=1

[test]
rpcuser=your_rpc_username
rpcpassword=your_rpc_password
rpcport=18332
```

Notes:
- Only **one** chain-selection option can be active at a time (`-testnet`,
  `-testnet4`, `-signet`, `-regtest`, or `-chain=`). If you pass `-testnet` on
  the command line while `bitcoin.conf` already sets a different chain (e.g.
  `testnet4=1` or `chain=test`), Bitcoin Core 25+ will refuse to start with:
  `Error: Invalid combination of -regtest, -signet, -testnet, -testnet4 and
  -chain. Can use at most one.` Fix by making sure only one is set, either in
  the conf file or via the command line, not both.
- Testnet3's default RPC port is **18332** (mainnet is 8332) — this must match
  `BITCOIN_RPC_PORT` in btcmesh's `.env`.
- Section headers like `[test]` scope settings to that specific network, so
  the same conf file can hold separate `rpcuser`/`rpcpassword` for mainnet,
  test, signet, etc. without conflicts.

## 3. Start the node

```bash
bitcoind -testnet -daemon
```

or in the foreground, to watch logs directly:

```bash
bitcoind -testnet
```

Check status:

```bash
bitcoin-cli -testnet -getinfo
bitcoin-cli -testnet getblockchaininfo
```

It will need to sync the testnet3 chain before it's fully useful (faster and
much smaller than mainnet, but still takes time on first run).

## 4. Troubleshooting: no peers found

If `getpeerinfo` returns an empty list despite having internet access, check
`debug.log` (in the testnet3 data subdirectory) for connection errors. A
common cause:

```
connect() to 127.0.0.1:9050 failed after wait: Connection refused (61)
```

This means `bitcoin.conf` has a `proxy=127.0.0.1:9050` (or `-proxy`) setting
routing all peer connections through Tor's default SOCKS5 port, but Tor isn't
running. Either:

- **Start Tor** (if you want peer traffic routed through it):
  ```bash
  brew services start tor   # macOS
  lsof -i :9050              # confirm it's listening
  ```
- **Or remove/comment out the `proxy=` line** in `bitcoin.conf` if Tor routing
  isn't needed for local testnet work, then restart `bitcoind`.

See the main [README's Tor Setup section](../README.md#tor-setup) if you do
want Tor connectivity (e.g. for connecting `btcmesh_server.py` to a remote
node over a `.onion` address).

## 5. Wire it up to btcmesh

In btcmesh's `.env` (see [README Setup Instructions](../README.md#setup-instructions)):

```env
BITCOIN_RPC_HOST=127.0.0.1
BITCOIN_RPC_PORT=18332
BITCOIN_RPC_USER=your_rpc_username
BITCOIN_RPC_PASSWORD=your_rpc_password
```

Or, instead of a fixed user/password, point at the auto-generated cookie file
(avoids storing a password in `.env`):

```env
BITCOIN_RPC_COOKIE=/Users/<you>/Library/Application Support/Bitcoin/testnet3/.cookie
```

Once the node is synced and reachable, `btcmesh_server.py` /
`btcmesh_server_gui.py` will be able to broadcast reassembled transactions to
it via RPC.

## 6. Exposing your own node's RPC over a `.onion` address

The Tor setup in the main README (`BITCOIN_RPC_HOST=<onion>`) assumes you're
*connecting to* a remote node that already has a `.onion` RPC address. To
expose your *own* local node's RPC as a hidden service instead — e.g. for
testing btcmesh's Tor code path against a node you control — you need to
configure Tor itself, not just `bitcoin.conf`.

### 6.1 Create/edit `torrc`

Find your Tor install's config directory (Homebrew on macOS:
`$(brew --prefix tor)/etc/tor/torrc`, often not created by default until you
add it yourself). Add:

```
HiddenServiceDir /opt/homebrew/var/lib/tor/bitcoin-rpc-testnet/
HiddenServicePort 18332 127.0.0.1:18332
```

(Adjust the path prefix for Intel Macs — `/usr/local` instead of
`/opt/homebrew` — or your platform's Tor data directory.)

**Gotcha:** Tor will refuse to start if the *parent* directory of
`HiddenServiceDir` doesn't already exist — it won't create missing
intermediate directories, only the final one. If `torrc` is being set up for
the first time, the parent (e.g. `/opt/homebrew/var/lib/tor/`) may not exist
yet either. Create it first:

```bash
mkdir -p /opt/homebrew/var/lib/tor
chmod 700 /opt/homebrew/var/lib/tor
```

Otherwise Tor's log (`$(brew --prefix tor)/var/log/tor.log` on Homebrew) will
show:
```
Error creating directory /opt/homebrew/var/lib/tor/bitcoin-rpc-testnet/: No such file or directory
Error loading rendezvous service keys
set_options: Bug: Acting on config options left us in a broken state. Dying.
```
and the service will fail to start entirely (`brew services info tor --json`
shows `"status": "error"`).

### 6.2 Restart Tor and get the address

```bash
brew services restart tor
cat /opt/homebrew/var/lib/tor/bitcoin-rpc-testnet/hostname
```

That file contains your new `<random>.onion` address. The private keys for
this hidden service live in that same directory — keep it around if you want
the address to stay stable across restarts.

A freshly created hidden service can take a minute or two to finish
publishing its descriptor to the Tor network before it's actually reachable
(even for self-connect testing from the same machine). If a test connection
fails immediately after creating it, wait a bit and retry before assuming
something's broken.

### 6.3 Test the tunnel before wiring up btcmesh

```bash
curl -v --max-time 60 --socks5-hostname 127.0.0.1:9050 \
  --user <rpcuser>:<rpcpassword> \
  --data-binary '{"jsonrpc":"1.0","id":"test","method":"getblockchaininfo","params":[]}' \
  -H 'content-type: text/plain;' \
  http://<your-address>.onion:18332/
```

Test the same credentials directly against `127.0.0.1:18332` (no
`--socks5-hostname`) too — if *both* fail with `401 Unauthorized`, the
problem is the credentials, not Tor. `btcmesh`'s `core/rpc_client.py` detects
`.onion` hosts automatically and routes through `socks5h://127.0.0.1:9050`
(`requests[socks]` is already a dependency), so once curl succeeds, `.env`
just needs:

```env
BITCOIN_RPC_HOST=<your-address>.onion
BITCOIN_RPC_PORT=18332
BITCOIN_RPC_USER=<rpcuser>
BITCOIN_RPC_PASSWORD=<rpcpassword>
```

### 6.4 If auth fails: use `rpcauth=`, not `rpcuser=`/`rpcpassword=`

Some `bitcoin.conf` generators (e.g. the jlopp config generator) produce an
`rpcauth=<user>:<salt>$<hash>` line instead of plaintext `rpcuser=`/
`rpcpassword=`. The plaintext password used to create that hash is **not**
recoverable from the conf file — if you don't know it, generate a fresh one
with Bitcoin Core's helper script (ships in the source tree under
`share/rpcauth/rpcauth.py`):

```bash
python3 <bitcoin-source>/share/rpcauth/rpcauth.py <username> <password>
```

This prints an `rpcauth=...` line to add to `bitcoin.conf`'s network section,
plus confirmation of the plaintext password. Add the line, restart `bitcoind`
(`bitcoin-cli stop`, wait for it to shut down, then start it again — it needs
to finish reloading the block index before RPC responds), and retest. Double
check the line was actually saved and matches what the script printed —
`rpcauth.py` uses a random salt each run, so re-running it (even with the
same password) produces a different-looking but equally valid line; a typo
during manual entry is the most common reason auth still fails after adding
it.
