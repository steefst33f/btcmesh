# Story 22.3 Implementation Plan: Create btcmesh_client_cli.py as thin CLI entry point

## Context

**Why this change:**
`btcmesh_cli.py` still contains the *original* monolithic implementation: argument parsing, chunking, a hand-rolled stop-and-wait ARQ loop, ACK/NACK/timeout handling, retry logic, and direct Meshtastic initialization — all mixed into one 679-line file. Stories 20-22.1 already extracted every piece of this business logic into dedicated, tested modules:

- Chunking, session creation, message parsing → `core/protocol.py`
- Meshtastic device connection → `transport/meshtastic_serial.py`
- Stop-and-wait ARQ, retries, ACK/NACK routing → `client/sender.py` (`TransactionSender`)

`btcmesh_gui.py` was refactored in Story 22.2 to use `TransactionSender` and no longer imports anything from `btcmesh_cli.py`. `btcmesh_cli.py` itself is now dead weight: a second, unused, untested-against-current-behavior implementation of logic that already lives (and is tested) elsewhere.

**Goal:**
Create `btcmesh_client_cli.py` as a thin wrapper — argument parsing, calls into `client/sender.py`, output formatting only — exactly mirroring the architecture `btcmesh_gui.py` already demonstrates. Then delete `btcmesh_cli.py` and its now-redundant business-logic tests.

**Outcome:**
A `btcmesh_client_cli.py` with no chunking logic, no transport setup, no ACK/NACK handling — just `argparse` → `TransactionSender`/`create_preview` → `print()`. `btcmesh_cli.py` is deleted. All docs and tests reference the new file.

---

## Current Flow (to be replaced)

```
main()
  → cli_main(args, injected_iface, injected_logger, injected_message_receiver)
      → argparse (only if args is None)
      → validate tx_hex inline (regex check)
      → if dry_run: chunk_transaction() + print BTC_TX lines directly → return 0
      → initialize_meshtastic_interface_cli() → raw SerialInterface
      → hand-rolled stop-and-wait loop:
          chunk_transaction(), pub.subscribe(on_receive_text_message_cli, ...),
          manual retry counters, manual timeout via queue.get(timeout=ACK_TIMEOUT),
          manual message parsing (string.split("|")),
          manual SystemExit(2)/(3)/(4) for different failure modes
      → iface.close() in finally
  → main(): catches ValueError → exit 1, RuntimeError → exit 2, Exception → exit 3
```

## New Flow

```
main()
  → cli_main(argv)
      → parse_args(argv)                          [argparse only]
      → validate_transaction_hex(args.tx)          [core/protocol.py — raises ValueError]
      → if args.dry_run: run_preview(args.tx)      [client.sender.create_preview — no transport]
      → else: run_send(args.destination, args.tx)
          → MeshtasticSerialTransport().connect(port)   [transport/meshtastic_serial.py]
          → TransactionSender(transport)                [client/sender.py]
          → sender.send_transaction(tx, dest,
                on_chunk_sending=print_sending,
                on_progress=print_progress,
                on_response_received=log_only)
          → print success (TXID) or error from SendResult
          → transport.disconnect() in finally
      → returns exit code directly (0/1/2)
  → main(): sys.exit(cli_main())
```

---

## Architecture Overview

### What `btcmesh_client_cli.py` contains

```
btcmesh_client_cli.py
├── parse_args(argv=None) -> argparse.Namespace   — CLI concern only
├── run_preview(tx_hex) -> int                    — dry-run: create_preview() + print
├── run_send(destination, tx_hex) -> int          — connect + TransactionSender + print
├── cli_main(argv=None) -> int                    — orchestration, returns exit code
└── main()                                        — sys.exit(cli_main())
```

No chunking, no transport setup beyond instantiating `MeshtasticSerialTransport`, no ACK/NACK parsing, no retry counters — all of that is already inside `client/sender.py` and `transport/meshtastic_serial.py`.

### What gets deleted

```
btcmesh_cli.py                    ← entire file (679 lines)
tests/test_btcmesh_cli.py         ← entire file (904 lines), EXCEPT the CLI-concern
                                     tests below, which get rewritten for the new file
```

Business-logic tests being removed are already covered elsewhere:

| Old test class (in test_btcmesh_cli.py) | Covered by |
|---|---|
| `TestMeshtasticCliInitializationStory62` | `tests/test_meshtastic_serial_transport.py` (40 tests) |
| `TestMeshtasticCliChunkedSendingStory63` | `tests/test_client_sender.py` (`TestTransactionSenderMultiChunk`, etc.) |
| `TestMeshtasticCliAckNackListeningStory64` | `tests/test_client_sender.py` (`TestTransactionSenderErrorHandling`, `TestTransactionSenderMessageFiltering`) |
| `TestCliStopAndWaitARQ` | `tests/test_client_sender.py` (`TestTransactionSenderMultiChunk`, `TestTransactionSenderRetry`) |
| `TestCliNackAndAbortHandling` | `tests/test_client_sender.py` (`TestTransactionSenderErrorHandling`) |
| `TestCliTimeoutAndRetriesOnNoAck` | `tests/test_client_sender.py` (`TestTransactionSenderRetry`) |

Genuinely CLI-concern tests being **preserved and rewritten** for the new file:

| Old test class | New coverage |
|---|---|
| `TestBtcmeshCliStory61` (arg parsing/validation) | `tests/test_btcmesh_client_cli.py` |
| `TestDryRunWithoutMeshtasticStory65` (dry-run behavior) | `tests/test_btcmesh_client_cli.py` |

---

## Implementation Steps

### Step 1: Create `btcmesh_client_cli.py`

```python
#!/usr/bin/env python3
"""Thin CLI entry point for sending a Bitcoin transaction via Meshtastic relay.

All business logic lives in client/sender.py (chunking, ARQ, retries) and
transport/meshtastic_serial.py (device connection). This file only handles:
argument parsing, output formatting, and exit codes.
"""
import argparse
import sys
import os

from core.config_loader import get_meshtastic_serial_port
from core.logger_setup import setup_logger
from core.protocol import validate_transaction_hex
from client.sender import TransactionSender, create_preview
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError

CLI_LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "logs", "btcmesh_client_cli.log"
)
cli_logger = setup_logger("btcmesh_client_cli", CLI_LOG_FILE)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Send a raw Bitcoin transaction via Meshtastic LoRa relay."
    )
    parser.add_argument(
        "-d", "--destination", required=True,
        help="Destination node ID (e.g., !abcdef12)",
    )
    parser.add_argument(
        "-tx", "--tx", required=True, help="Raw transaction hex string"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only show the chunking preview, do not send",
    )
    return parser.parse_args(argv)


def run_preview(tx_hex: str) -> int:
    """Show how the transaction would be chunked, without sending."""
    preview = create_preview(tx_hex)
    print(f"Preview: {preview.total_chunks} chunk(s)")
    for chunk in preview.chunks:
        print(chunk.wire_format)
    return 0


def run_send(destination: str, tx_hex: str) -> int:
    """Connect to the Meshtastic device and send the transaction."""
    transport = MeshtasticSerialTransport()
    try:
        transport.connect(get_meshtastic_serial_port())
    except TransportConnectionError as e:
        print(f"Failed to connect to Meshtastic device: {e}", file=sys.stderr)
        cli_logger.error(f"Failed to connect: {e}")
        return 2

    try:
        sender = TransactionSender(transport)

        def on_chunk_sending(chunk_num, total, attempt, wire_format):
            if attempt > 1:
                print(f"Retrying chunk {chunk_num}/{total} (attempt {attempt})...")
            else:
                print(f"Sending chunk {chunk_num}/{total}...")
            cli_logger.info(f"Sending chunk {chunk_num}/{total} (attempt {attempt}): {wire_format}")

        def on_progress(chunk_num, total):
            print(f"Received ACK for chunk {chunk_num}/{total}")
            cli_logger.info(f"ACK for chunk {chunk_num}/{total}")

        def on_response_received(message_text):
            cli_logger.debug(f"Received: {message_text}")

        result = sender.send_transaction(
            tx_hex, destination,
            on_progress=on_progress,
            on_chunk_sending=on_chunk_sending,
            on_response_received=on_response_received,
        )
    finally:
        transport.disconnect()

    if result.success:
        print(f"Transaction successfully broadcast by relay. TXID: {result.txid}")
        cli_logger.info(f"Success: TXID {result.txid}")
        return 0

    print(f"Transaction failed: {result.error}", file=sys.stderr)
    cli_logger.error(f"Failed: {result.error}")
    return 1


def cli_main(argv=None) -> int:
    """Thin CLI orchestration. Returns process exit code."""
    args = parse_args(argv)

    try:
        validate_transaction_hex(args.tx)
    except ValueError as e:
        print(f"Invalid raw transaction hex: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        return run_preview(args.tx)
    return run_send(args.destination, args.tx)


def main():
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
```

### Step 2: Create `tests/test_btcmesh_client_cli.py`

Covers only CLI-layer concerns (mirrors `TestBtcmeshCliStory61` and `TestDryRunWithoutMeshtasticStory65` from the old file, adapted to the new function names/signatures):

- `parse_args()`: valid args parse correctly; missing `--destination`/`--tx` raises `SystemExit(2)` (argparse's own behavior)
- `cli_main()`: invalid hex / odd-length hex → prints error, returns 1
- `cli_main(--dry-run)`: prints chunk preview lines, returns 0, **does not** call `MeshtasticSerialTransport` at all (patch it and assert `assert_not_called()`)
- `run_send()`: connection failure (`TransportConnectionError`) → prints error, returns 2, `TransactionSender`/`send_transaction` never called
- `run_send()`: successful send (mocked `TransactionSender.send_transaction` returning a successful `SendResult`) → prints TXID, returns 0
- `run_send()`: failed send (mocked `SendResult(success=False, error=...)`) → prints error, returns 1
- `transport.disconnect()` is called even when `send_transaction` raises (assert via mock in a `finally`-path test)

### Step 3: Delete `btcmesh_cli.py` and `tests/test_btcmesh_cli.py`

Both removed entirely once Step 2's tests pass and the mapping table above confirms no coverage gap.

### Step 4: Update documentation references

| File | Change |
|---|---|
| `README.md` | Replace all `btcmesh_cli.py` references (title, description, structure tree, "Running the Client" section, setup step 5) with `btcmesh_client_cli.py` |
| `CLAUDE.md` | Line 40's example test command (`tests.test_btcmesh_cli...`) → `tests.test_btcmesh_client_cli...`; line 210's component description; line 262/285's `CHUNK_SIZE`/`EXAMPLE_RAW_TX` references (see Key Design Decision 3 below) |
| `project/architecture.md` | Historical/target-state doc — no change needed, it already documents `btcmesh_client_cli.py` as the target filename |
| `btcmesh_gui.py` | Fix stale module docstring: *"This GUI wraps the btcmesh_cli module..."* → no longer true since Story 22.2; update to describe the actual current architecture |

### Step 5: Full test suite run + manual verification

See Verification section below.

---

## Critical Files

| File | Change |
|---|---|
| `btcmesh_client_cli.py` | **New** — thin CLI wrapper (~100 lines vs. old 679) |
| `btcmesh_cli.py` | **Deleted** |
| `tests/test_btcmesh_client_cli.py` | **New** — CLI-concern tests only |
| `tests/test_btcmesh_cli.py` | **Deleted** |
| `README.md` | Update all `btcmesh_cli.py` → `btcmesh_client_cli.py` references |
| `CLAUDE.md` | Update test command example and component list |
| `btcmesh_gui.py` | Fix one stale docstring line (no functional change) |

---

## Key Design Decisions

### 1. Exit codes simplified (0 / 1 / 2), dropping old granularity
The old CLI's hand-rolled ARQ loop raised `SystemExit(2)` for abort/max-retries, `SystemExit(3)` for NACK, `SystemExit(4)` for no final confirmation — because it tracked failure *reasons* itself. `TransactionSender.send_transaction()` collapses all of that into a single `SendResult(success=False, error=str)` — the reason is a string, not a distinct code path. The new CLI exit codes are:
- `0` — success
- `1` — validation error (bad hex) or send failure (any `SendResult.error`)
- `2` — could not connect to the Meshtastic device

This is a deliberate simplification consistent with what the underlying `SendResult` actually exposes. If finer-grained exit codes are needed later, that's a `client/sender.py` change (e.g. an error-category enum on `SendResult`), not something to fake at the CLI layer.

### 2. `cli_main()` returns exit codes directly, never raises for control flow
The old CLI raised `ValueError`/`RuntimeError` from `cli_main()` for `main()` to catch and map to exit codes. The new `cli_main()` returns an `int` directly in all cases — simpler to test (no `assertRaises` needed for the common paths) and matches the "thin wrapper" spirit: no exception-based control flow for expected outcomes.

### 3. `EXAMPLE_RAW_TX` dropped entirely
Defined in the old file but never referenced by any of its own logic (dead weight — pure copy-paste reference). Already documented in `project/reference_materials.md` per CLAUDE.md. Not carried into the new file.

### 4. No new `--port` flag
Old CLI never exposed a port-override flag either (always resolved via `.env`/auto-detect through `get_meshtastic_serial_port()`). Staying at behavioral parity — not adding scope beyond what Story 22.3 asks for.

### 5. Log file and logger renamed to match the new filename
`btcmesh_cli.log` / `"btcmesh_cli"` → `btcmesh_client_cli.log` / `"btcmesh_client_cli"`. Internal artifact only, not part of any documented external contract.

### 6. `tests/test_integration.py` untouched
Only contains a commented-out, unused `# from btcmesh_cli import cli_main` reference inside a stub test class with no implemented body. No actual dependency to update.

---

## Verification

1. Run the full suite: `python -m unittest discover -s tests -p 'test_*.py'` — expect the same total minus (904-line file's ~30 business-logic tests removed) plus (new CLI-concern tests added), all passing.
2. Confirm `btcmesh_cli.py` no longer exists and nothing imports it: `grep -rn "btcmesh_cli" --include="*.py" .` should return no hits outside historical comments (`client/sender.py`'s docstring, `project/architecture.md`).
3. Manually run the new CLI end-to-end against real hardware:
   - `python btcmesh_client_cli.py --dry-run -d !abcdef12 -tx <RAW_TX_HEX>` — verify chunk preview prints, no device connection attempted.
   - `python btcmesh_client_cli.py -d <real destination node> -tx <RAW_TX_HEX>` — verify it connects, sends chunks with progress printed, and reports success/TXID or a clear error.
4. Confirm `README.md` and `CLAUDE.md` no longer reference `btcmesh_cli.py` as a runnable file.
