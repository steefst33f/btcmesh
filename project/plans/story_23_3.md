# Story 23.3 Implementation Plan: Create btcmesh_server_cli.py as thin CLI entry point

## Context

**Why this change:**
`btcmesh_server.py` still contains the *original* monolithic server implementation (809 lines): Meshtastic packet parsing/dispatch (`on_receive_text_message`), reply sending (`send_meshtastic_reply`), device initialization (`initialize_meshtastic_interface`), and the main polling loop — all mixed into one file with no argparse (it's `.env`-only, zero CLI flags today). Stories 20-23.2 already extracted this into dedicated, tested modules:

- Chunk reassembly, ACK/NACK sending, RPC broadcast → `server/receiver.py` (`TransactionReceiver`, Story 23.1)
- Meshtastic device connection → `transport/meshtastic_serial.py`
- `btcmesh_server_gui.py` was refactored in Story 23.2 to use `TransactionReceiver` directly and no longer imports anything from `btcmesh_server.py` (confirmed — no import found anywhere outside its own test file).

This is the direct sibling of Story 22.3 (which did the same thing for the client side, producing `btcmesh_client_cli.py`). `btcmesh_server.py` is now dead weight: a second, unused implementation of logic that already lives (and is tested) elsewhere — except for one wrinkle described below.

**The wrinkle (bigger than the client-side story had):** `tests/test_btcmesh_server.py` (1905 lines, 65 tests, 13 classes) is not purely redundant. Digging in, **8 of its 13 classes (30 tests) directly import and test `core/` modules that have no other test file at all**: `core/reassembler.py`, `core/transaction_parser.py`, `core/rpc_client.py`, and parts of `core/config_loader.py`. These tests were historically written before those modules were extracted into `core/`, and just never got moved. Deleting the file wholesale (like `tests/test_btcmesh_cli.py` was deleted in Story 22.3) would silently drop the only coverage those modules have. This story needs to **split** that test file, not just delete it.

**Goal:** Create `btcmesh_server_cli.py` as a thin wrapper — config loading, connect, wire `TransactionReceiver`'s callbacks to logging, run until Ctrl+C — mirroring `btcmesh_client_cli.py`'s shape and reusing the exact callback set already proven in `btcmesh_server_gui.py`'s `run_server()` (Story 23.2 plus the two follow-up fixes this session: wire-level logging and narrative chunk/broadcast status logging). Then delete `btcmesh_server.py`, after relocating the 30 genuinely-homeless `core/` tests into their own new test files and confirming the remaining 35 tests are truly redundant with `tests/test_server_receiver.py` / `tests/test_meshtastic_serial_transport.py`.

**Outcome:** A `btcmesh_server_cli.py` with no reassembly logic, no transport setup, no RPC handling — just config → `TransactionReceiver` → logging → loop. `btcmesh_server.py` is deleted. `core/reassembler.py`, `core/transaction_parser.py`, `core/rpc_client.py`, `core/config_loader.py` each have (or gain) their own proper test file. All docs updated.

---

## Current Flow (to be replaced)

```
main(stop_event=None, rpc_config=None, serial_port=None, reassembly_timeout=None, session_update_callback=None)
  → load reassembly timeout (param > env > default), construct TransactionReassembler
  → construct TransactionHistory
  → try: load/connect BitcoinRPCClient — except: bitcoin_rpc=None, log error, CONTINUE (not fatal)
  → initialize_meshtastic_interface(port) → raw SerialInterface (own reimplementation,
    not transport/meshtastic_serial.py)
  → pub.subscribe(on_receive_text_message, "meshtastic.receive")
  → while True loop (GUI-injection params: stop_event, session_update_callback):
      - on_receive_text_message() dispatch per packet: filters DM-to-self, extracts
        chunk text, calls transaction_reassembler.add_chunk(), sends ACK/NACK via
        send_meshtastic_reply(), broadcasts via bitcoin_rpc on completion
      - periodic cleanup_stale_sessions() → NACK + history.add()
      - time.sleep(1)
  → except KeyboardInterrupt: log and break
  → finally: meshtastic_iface.close()
```

## New Flow

```
main()
  → sys.exit(run_server())
      → load_app_config(), resolve serial_port (get_meshtastic_serial_port() or -p flag)
      → MeshtasticSerialTransport().connect(serial_port) — fatal if it fails (return 2)
      → try: BitcoinRPCClient(load_bitcoin_rpc_config()) — except: rpc_client=None,
        log error, CONTINUE (matches old/GUI behavior — Meshtastic keeps receiving
        even if RPC is down; only the eventual broadcast fails)
      → TransactionHistory()
      → build_receiver(transport, rpc_client, reassembly_timeout, history)
            — wires on_chunk_received/on_broadcast_started/on_broadcast/on_error/
              on_wire_sent/on_wire_received to server_logger calls + history.add(),
              exactly mirroring btcmesh_server_gui.py's run_server() closures
      → loop: while True: check_timeouts() every ~10s, time.sleep(1)
      → except KeyboardInterrupt: log, break
      → finally: transport.disconnect(); return 0
```

---

## Architecture Overview

### What `btcmesh_server_cli.py` contains

```
btcmesh_server_cli.py
├── parse_args(argv=None) -> argparse.Namespace   — CLI concern only (-p/--port)
├── build_receiver(transport, rpc_client, reassembly_timeout, history) -> TransactionReceiver
│                                                  — wires callbacks to server_logger
├── run_server(port=None) -> int                   — connect + loop, returns exit code
└── main()                                          — sys.exit(run_server(...))
```

No reassembly logic, no packet parsing, no ACK/NACK string building, no RPC client internals — all of that is already inside `server/receiver.py`, `transport/meshtastic_serial.py`, and `core/rpc_client.py`.

### Test file split (the real scope of this story)

| Old class in `test_btcmesh_server.py` | Tests | Destination |
|---|---|---|
| `TestTransactionReassemblerStory21` | 5 | **New** `tests/test_reassembler.py` — directly tests `core.reassembler.TransactionReassembler`, no `btcmesh_server` dependency |
| `TestHexValidationStory22` | 3 | Same new file — 2 tests are pure stdlib `int(x,16)` checks (arguably vacuous, kept for parity), 1 exercises `add_chunk()` concatenation |
| `TestTransactionDecodeStory23` | 2 | **New** `tests/test_transaction_parser.py` — tests `core.transaction_parser.decode_raw_transaction_hex` |
| `TestTransactionSanityChecksStory31` | 3 | Same new file — tests `core.transaction_parser.basic_sanity_check` |
| `TestBitcoinRpcConfigStory41` | 3 | **New** `tests/test_config_loader.py` — tests `core.config_loader.load_bitcoin_rpc_config` |
| `TestReassemblyTimeoutConfigStory52` | 4 | Same new file — tests `core.config_loader.load_reassembly_timeout` |
| `TestBitcoinRpcConnectionStory42` | 7 | **New** `tests/test_rpc_client.py` — tests `core.rpc_client.BitcoinRPCClient` connection |
| `TestBitcoinRpcBroadcastStory43` | 3 | Same new file — tests `BitcoinRPCClient.broadcast_transaction` |
| `TestMeshtasticInitialization` | 9 | **Deleted** — redundant with `tests/test_meshtastic_serial_transport.py` (device connect/error paths, already covers autodetect/explicit-port/no-device/generic-error scenarios) |
| `TestMessageHandling` | 15 | **Deleted** — redundant with `tests/test_server_receiver.py`'s `_on_message` tests (chunk dispatch, NACK on invalid/mismatched, format validation) |
| `TestMeshtasticReplySending` | 7 | **Deleted** — redundant with `test_server_receiver.py`'s `_send`/`_send_nack` tests + `test_meshtastic_serial_transport.py`'s `send()` error tests |
| `TestMultipleConcurrentSessions` | 1 | **Deleted** — redundant with `test_server_receiver.py` (reassembler itself is keyed per-sender; multi-session independence is a reassembler property, covered by real (non-mocked) reassembler use across multiple `test_server_receiver.py` tests with distinct sender/session ids) |
| `TestAckNackAndErrorHandling` | 3 | **Deleted** — redundant with `test_server_receiver.py`'s ACK/NACK end-to-end tests |

Net: 30 tests relocated into 3 new `core/`-module test files (finally giving those modules proper homes), 35 tests deleted as redundant, `tests/test_btcmesh_server.py` itself deleted.

**Verification step for the "deleted" rows:** before deleting, diff each old test's scenario against `test_server_receiver.py`/`test_meshtastic_serial_transport.py` by name to confirm an equivalent exists (same approach Story 22.3 used) — if any gap is found, add the missing scenario to the receiving file rather than silently dropping coverage.

### What gets deleted

```
btcmesh_server.py                 ← entire file (809 lines)
tests/test_btcmesh_server.py      ← entire file (1905 lines), split as above first
```

---

## Implementation Steps

### Step 1: Create the 3 new `core/`-module test files

Move (not copy) the 8 classes listed above verbatim into `tests/test_reassembler.py`, `tests/test_transaction_parser.py`, `tests/test_rpc_client.py`, `tests/test_config_loader.py`, adjusting only file-level imports (each test already imports its target directly from `core.xxx`, e.g. `from core.reassembler import TransactionReassembler` — no test-body changes needed). Run each new file standalone to confirm all pass unchanged.

### Step 2: Create `btcmesh_server_cli.py`

```python
#!/usr/bin/env python3
"""Thin CLI entry point for running the BTCMesh relay server.

All business logic lives in server/receiver.py (chunk reassembly, RPC
broadcast) and transport/meshtastic_serial.py (device connection). This
file only handles: config loading, startup/shutdown, and logging.
"""
import argparse
import sys
import time

from core.config_loader import (
    get_meshtastic_serial_port,
    load_app_config,
    load_bitcoin_rpc_config,
    load_reassembly_timeout,
)
from core.logger_setup import server_logger
from core.reassembler import TransactionReassembler
from core.rpc_client import BitcoinRPCClient
from core.transaction_history import TransactionHistory
from server.receiver import TransactionReceiver, ChunkReceived, BroadcastResult
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError

CHECK_TIMEOUTS_INTERVAL_SECONDS = 10


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the BTCMesh relay server."
    )
    parser.add_argument(
        "-p", "--port",
        help="Meshtastic serial port to use (e.g. /dev/ttyUSB0). "
             "Overrides MESHTASTIC_SERIAL_PORT in .env. If neither is set, "
             "auto-detects - which fails or picks unpredictably if more than "
             "one device is connected.",
    )
    return parser.parse_args(argv)


def build_receiver(transport, rpc_client, reassembly_timeout, history) -> TransactionReceiver:
    """Wire TransactionReceiver's callbacks to server_logger + history - the
    same callback set and log wording btcmesh_server_gui.py's Activity Log
    uses, just logged instead of pushed to a GUI queue."""

    def on_chunk_received(evt: ChunkReceived):
        server_logger.info(f"[{evt.session_id}] Received chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}")
        if evt.chunk_num < evt.total_chunks:
            server_logger.info(f"[{evt.session_id}] Requesting chunk {evt.chunk_num + 1}/{evt.total_chunks}...")
        else:
            server_logger.info(f"[{evt.session_id}] All {evt.total_chunks} chunks received. Reassembly successful.")

    def on_broadcast_started(session_id, sender_id):
        server_logger.info(f"[{session_id}] Broadcasting transaction to Bitcoin network...")

    def on_broadcast(result: BroadcastResult):
        if result.success:
            server_logger.info(f"[{result.session_id}] Broadcast success. TXID: {result.txid}")
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="success", txid=result.txid, raw_tx=result.raw_tx)
        else:
            server_logger.error(f"[{result.session_id}] Broadcast failed: {result.error}")
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="failed", error=result.error, raw_tx=result.raw_tx)

    def on_error(session_id, sender_id, error):
        server_logger.warning(f"[{session_id}] Error from {sender_id}: {error}")
        history.add(session_id=session_id, sender=sender_id, status="failed", error=error, raw_tx=None)

    def on_wire_sent(message_text):
        server_logger.info(f"  -> {message_text}")

    def on_wire_received(message_text):
        server_logger.info(f"  <- {message_text}")

    return TransactionReceiver(
        transport, rpc_client,
        reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
        on_chunk_received=on_chunk_received,
        on_broadcast_started=on_broadcast_started,
        on_broadcast=on_broadcast,
        on_error=on_error,
        on_wire_sent=on_wire_sent,
        on_wire_received=on_wire_received,
    )


def run_server(port=None) -> int:
    """Connect, run until Ctrl+C, then disconnect. Returns process exit code."""
    load_app_config()

    resolved_port = port or get_meshtastic_serial_port()
    server_logger.info(f"Connecting to Meshtastic device{f' ({resolved_port})' if resolved_port else ' (auto-detect)'}...")
    transport = MeshtasticSerialTransport()
    try:
        transport.connect(resolved_port)
    except TransportConnectionError as e:
        server_logger.error(f"Failed to connect to Meshtastic device: {e}")
        return 2
    server_logger.info(f"Connected to Meshtastic device. Node ID: {transport.local_node_id}")

    # Match old behavior: a failed RPC connection does not stop the server -
    # Meshtastic keeps receiving/reassembling/ACKing chunks, only the eventual
    # broadcast step fails once a transaction actually completes.
    try:
        rpc_client = BitcoinRPCClient(load_bitcoin_rpc_config())
        server_logger.info(f"Connected to Bitcoin Core RPC node. Chain: {rpc_client.chain}")
    except Exception as e:
        rpc_client = None
        server_logger.error(f"Failed to connect to Bitcoin Core RPC node: {e}. Continuing without RPC connection.")

    reassembly_timeout, _source = load_reassembly_timeout()
    history = TransactionHistory()
    receiver = build_receiver(transport, rpc_client, reassembly_timeout, history)

    server_logger.info("Server started. Listening for incoming transactions... (Ctrl+C to stop)")
    try:
        last_cleanup = time.time()
        while True:
            now = time.time()
            if now - last_cleanup >= CHECK_TIMEOUTS_INTERVAL_SECONDS:
                receiver.check_timeouts()
                last_cleanup = now
            time.sleep(1)
    except KeyboardInterrupt:
        server_logger.info("Server shutting down by user request (Ctrl+C).")
    finally:
        transport.disconnect()
    return 0


def main():
    args = parse_args()
    sys.exit(run_server(args.port))


if __name__ == "__main__":
    main()
```

### Step 3: Create `tests/test_btcmesh_server_cli.py`

CLI-layer concerns only, mirroring `tests/test_btcmesh_client_cli.py`'s structure:
- `parse_args()`: `-p`/`--port` parses correctly; omitted defaults to `None`
- `run_server()`: connection failure (`TransportConnectionError`) → logs error, returns 2, `BitcoinRPCClient`/`TransactionReceiver` never constructed
- `run_server()`: RPC connection failure → logs error, continues (receiver still built with `rpc_client=None`) — this is the exact bug fixed in Story 23.2's GUI equivalent; worth a dedicated regression test here too
- `run_server()`: explicit `port` argument passed straight to `transport.connect()`, taking precedence over `get_meshtastic_serial_port()`
- `run_server()`: omitted `port` falls back to `get_meshtastic_serial_port()`'s return value
- `build_receiver()`: constructs `TransactionReceiver` with all 6 callbacks wired (assert via `TransactionReceiver.__init__`'s call kwargs, patching the class)
- `KeyboardInterrupt` during the loop → `transport.disconnect()` still called (via `finally`), returns 0

### Step 4: Delete `btcmesh_server.py` and `tests/test_btcmesh_server.py`

Once Steps 1-3 pass and the mapping table's "deleted" rows are spot-verified against their replacement files.

### Step 5: Update documentation references

| File | Change |
|---|---|
| `README.md` | Replace the `## Running the Server (btcmesh_server.py)` section and all other `btcmesh_server.py` mentions (title, description, dir tree) with `btcmesh_server_cli.py`; document the new `-p`/`--port` flag |
| `project/architecture.md` | Historical/target-state doc — already documents `btcmesh_server_cli.py` as the target filename, no change needed |
| `project/next_steps.md` | Line 37's `TRX_CHUNK_BUFFER` cleanup TODO becomes moot (the whole file it lives in is deleted) — remove the stale TODO line |

`project/bitcoin_testnet_setup.md`, `project/issues.txt`, `project/plans/story_23_1.md`, `project/plans/story_23_2.md`, `project/arq-tasks.txt` all reference `btcmesh_server.py` only as historical narrative (past-tense descriptions of what the old code did) — left as-is, same treatment Story 22.3 gave equivalent historical mentions.

### Step 6: Full test suite run + manual verification

See Verification section below.

---

## Critical Files

| File | Change |
|---|---|
| `btcmesh_server_cli.py` | **New** — thin CLI wrapper (~110 lines vs. old 809) |
| `btcmesh_server.py` | **Deleted** |
| `tests/test_btcmesh_server_cli.py` | **New** — CLI-concern tests only |
| `tests/test_reassembler.py` | **New** — 8 tests moved from `test_btcmesh_server.py` |
| `tests/test_transaction_parser.py` | **New** — 5 tests moved |
| `tests/test_rpc_client.py` | **New** — 10 tests moved |
| `tests/test_config_loader.py` | **New** — 7 tests moved |
| `tests/test_btcmesh_server.py` | **Deleted** (1905 lines, after the above extractions) |
| `README.md` | Update all `btcmesh_server.py` references |
| `project/next_steps.md` | Remove one stale TODO line |

---

## Key Design Decisions

### 1. Reuse the existing `server_logger` ("btcmesh_server" / `logs/btcmesh_server.log`), don't rename it — deviation from the client-side precedent
Story 22.3 renamed the client's logger/log file to match its new filename (`btcmesh_cli` → `btcmesh_client_cli`), reasoning it was an internal artifact with no external contract. The server side is different: `core/reassembler.py` **itself** already calls `server_logger.info/warning/error(...)` directly (pre-existing architecture debt — `core/` is supposed to be pure/logging-free per this project's own layering rules, but this module predates that rule and nobody's cleaned it up). That means reassembly-session logging (new session started, chunk added, timeout, etc.) is going to show up under the `"btcmesh_server"` logger name regardless of what this CLI does. Introducing a second logger name (`"btcmesh_server_cli"`) for the CLI's own narrative/wire lines would split one continuous operational narrative across two logger names in the same file for no real benefit. Keeping `server_logger` as-is also preserves the exact log file path already referenced in `project/bitcoin_testnet_setup.md`. Cleaning up `core/reassembler.py`'s embedded logging is real architecture debt worth fixing eventually, but it's out of scope here — flagging it as a candidate for `project/issues.txt` rather than doing it in this story.

### 2. Wire-format logs (raw BTC_TX/CHUNK_ACK/ACK/NACK text) at INFO, not DEBUG
The old `on_receive_text_message` logged the raw incoming message text at INFO level (`"Direct text from X: '...'"`). Logging `on_wire_sent`/`on_wire_received` at INFO (rather than DEBUG, which `server_logger`'s default level would silently drop) keeps this CLI at least as verbose as the file it's replacing, and matches what `btcmesh_server_gui.py`'s Activity Log now shows by default. This means the terminal/log file gets both a narrative line and a raw wire line per event (mirroring the GUI's two-tier display) — more verbose than strictly minimal, but consistent with "replacement for btcmesh_server.py" rather than a quieter redesign.

### 3. No `stop_event`/`session_update_callback` parameters on `run_server()`
The old `main()`'s signature carried GUI-injection hooks (`stop_event`, `session_update_callback`) because the old GUI called into `btcmesh_server.main()` directly. Since Story 23.2, `btcmesh_server_gui.py` builds its own `TransactionReceiver` and never calls into this file at all — confirmed via import search, zero remaining callers need these hooks. Dropping them keeps `run_server()` a genuinely simple, standalone blocking loop relying on `KeyboardInterrupt`, exactly like `btcmesh_client_cli.py`'s equivalent simplicity.

### 4. Add `-p`/`--port`, matching the client CLI's exact precedent
The old server had zero CLI flags (`.env`-only). Story 22.3 added `-p`/`--port` to the client CLI after discovering that auto-detect becomes ambiguous/unreliable with more than one Meshtastic device connected (Issue 9's underlying whitelist bug resurfacing on a path that bypasses `scan_meshtastic_devices()`). The exact same underlying risk applies to the server's auto-detect path. Adding the flag now, proactively, rather than waiting to rediscover the same gap during hardware testing.

### 5. Test-file split is mandatory, not optional cleanup
Unlike Story 22.3 (where `tests/test_btcmesh_cli.py` was cleanly, fully redundant), 30 of `test_btcmesh_server.py`'s 65 tests are the *only* coverage `core/reassembler.py`, `core/transaction_parser.py`, and `core/rpc_client.py` have. This story extracts them into proper dedicated test files rather than deleting them — a larger scope than the story's one-line acceptance criteria implies, but necessary to avoid a silent coverage loss.

---

## Verification

1. Run the full suite after Step 1 (new test files created, old file untouched): expect all-passing with the 30 relocated tests now also collected from their new locations (temporarily double-counted until Step 4's deletion).
2. Run the full suite after Step 4 (old files deleted): expect total count = previous total - 65 (old file) + ~10-15 (new CLI-concern tests), all passing.
3. Confirm `btcmesh_server.py` no longer exists and nothing imports it: `grep -rn "btcmesh_server\b" --include="*.py" .` should return no hits outside historical comments and the `logs/btcmesh_server.log` / `"btcmesh_server"` logger-name string (Decision 1).
4. Manually run the new CLI end-to-end against real hardware (devices were available as of the last session):
   - `python btcmesh_server_cli.py` — verify it connects (auto-detect), logs RPC connection status, and shows "Server started..."
   - `python btcmesh_server_cli.py -p <device port>` — verify it connects to the specified port
   - Send a real transaction from `btcmesh_client_cli.py` while this is running — verify the full narrative (received chunk / requesting next / reassembly successful / broadcasting / broadcast success or failure) appears in both the terminal and `logs/btcmesh_server.log`, and that Ctrl+C shuts it down cleanly (transport disconnects, port is freed).
5. Confirm `README.md` no longer references `btcmesh_server.py` as a runnable file.
