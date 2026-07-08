# Story 22.2 Implementation Plan: Refactor btcmesh_gui.py to use client/sender.py

## Context

**Why this change:**
The GUI currently sends transactions by calling `cli_main()` in a background thread, capturing its stdout via `PrintCapture` and log output via `QueueLogHandler`, then parsing strings to detect success or failure. This couples the GUI directly to the CLI layer and makes the GUI impossible to test properly without mocking the CLI.

**Goal:**
Replace the `cli_main()` call with a direct call to `TransactionSender` from `client/sender.py`, making the GUI a thin wrapper that only handles UI concerns. All sending logic moves to the client layer where it belongs.

**Outcome:**
A `btcmesh_gui.py` that imports nothing from `btcmesh_cli.py`, with a clean `_send_transaction_thread()` that creates a `TransactionSender`, wires up callbacks, and puts typed result tuples into the queue. The `process_result()` pure function handles these typed tuples cleanly without any string parsing.

---

## Current Flow (to be replaced)

```
on_send_pressed()
  → _send_transaction_thread() [background thread]
      → cli_main(args, injected_iface, injected_logger)
          stdout captured via PrintCapture (checks abort_requested flag)
          logs via QueueLogHandler
      → result_queue.put(('print', text)) per stdout line
      → result_queue.put(('cli_finished', exit_code))
  → _check_results() [polling on Clock]
      → process_result(('print', text)) → parse for "TXID:" to detect success
```

## New Flow

```
on_send_pressed()
  → _send_transaction_thread() [background thread]
      → sender.send_transaction(tx_hex, dest,
            on_chunk_sending=callback,    ← fires before each send attempt
            on_progress=callback,         ← fires after each chunk ACK
            on_response_received=callback ← fires on incoming ACK/NACK wire messages)
          on_chunk_sending(chunk_num, total, attempt, wire_format) → result_queue.put(('chunk_sending', ...))
          on_progress(chunk_num, total)                            → result_queue.put(('progress', ...))
          on_response_received(message_text)                       → result_queue.put(('wire_received', ...))
          checks sender._abort_event between chunks
      → result_queue.put(('send_result', SendResult))
  → _check_results() [polling on Clock]
      → process_result(('send_result', SendResult)) → show success/error
```

---

## Architecture Overview

### What Gets Removed

The GUI currently contains CLI-coupling artifacts that are no longer needed:

```
btcmesh_gui.py — REMOVE:
├── from btcmesh_cli import cli_main, EXAMPLE_RAW_TX
├── class QueueLogHandler          ← CLI log capture
├── class PrintCapture             ← CLI stdout capture
├── class AbortedException         ← CLI abort mechanism
├── self.abort_requested flag      ← CLI abort flag
├── _send_transaction_thread()     ← replaces entirely
└── _get_own_node_id()             ← duplicates meshtastic_utils.get_own_node_id()
```

### What Gets Added to client/sender.py

`TransactionSender.send_transaction()` needs two new callbacks and an abort mechanism:

1. **`on_chunk_sending(chunk_num, total, attempt, wire_format)`** — called just before each `transport.send()`, including retries. Gives the GUI visibility into what's being sent and when retries happen.

2. **`on_response_received(message_text)`** — called in `_on_message()` for all incoming messages that match an active session. Gives the GUI the raw ACK/NACK wire messages.

3. **`abort()` method + `_abort_event: threading.Event`** — replaces the current `abort_requested` flag. Checked between chunk sends in the send loop.

### Activity Log Design

Currently the GUI always shows debug-level detail (the injected logger is set to `logging.DEBUG`). The new design preserves this by always firing the wire message callbacks:

| Event | Log message |
|-------|-------------|
| Before send | `Sending chunk 1/3...` |
| Before send (retry) | `Sending chunk 1/3 (retry 1)...` |
| Wire message sent | `  → BTC_TX\|a1b2c\|1/3\|020000...` |
| Wire message received | `  ← BTC_CHUNK_ACK\|a1b2c\|1\|REQUEST_CHUNK\|2` |
| After ACK | `Chunk 1/3 sent` |
| After final chunk ACK | `Chunk 3/3 sent — waiting for broadcast...` |
| Success | success popup with TXID |
| Error | `Error: Insufficient fee` |
| Abort | `Transaction aborted by user` |

A verbose toggle (to hide wire messages) is a future story — current behavior is always-verbose.

---

## Implementation Steps

### Step 1a: Add protocol-level callbacks to `send_transaction()` (`client/sender.py`)

Add two new optional parameters to `send_transaction()`:

```python
def send_transaction(
    self,
    tx_hex: str,
    destination: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_chunk_sending: Optional[Callable[[int, int, int, str], None]] = None,
    # on_chunk_sending(chunk_num, total, attempt, wire_format)
    on_response_received: Optional[Callable[[str], None]] = None,
    # on_response_received(message_text)
) -> SendResult:
```

**`on_chunk_sending`** — call inside `_send_all_chunks()`, just before `self.transport.send()`:
```python
attempt = send_session.retry_counts.get(chunk_num, 0) + 1
if on_chunk_sending:
    on_chunk_sending(chunk_num, total, attempt, wire_format)
self.transport.send(wire_format, destination)
```

**`on_response_received`** — stored as instance variable, called in `_on_message()`:
```python
def _on_message(self, message_text: str, sender_id: str) -> None:
    if self._on_response_received:
        self._on_response_received(message_text)
    ...
```

Store `on_response_received` as `self._on_response_received`, set at the start of `send_transaction()` and reset to `None` in the `finally` block.

Pass `on_chunk_sending` down through `_send_all_chunks()` — add it as a parameter.

### Step 1b: Add `abort()` to `TransactionSender` (`client/sender.py`)

Add a `threading.Event` to `__init__`:
```python
self._abort_event = threading.Event()
```

New public method:
```python
def abort(self) -> None:
    self._abort_event.set()
```

Check in `_send_all_chunks()` after each successful chunk ACK (before sending next chunk):
```python
if self._abort_event.is_set():
    send_session.error = "Aborted by user"
    send_session.failed = True
    return
```

Reset at start of `send_transaction()`:
```python
self._abort_event.clear()
```

### Step 2: Replace Meshtastic init in `btcmesh_gui.py`

Replace `self.iface = SerialInterface(...)` with:
```python
from transport.meshtastic_serial import MeshtasticSerialTransport

self.transport = MeshtasticSerialTransport()
self.transport.connect(port)
self.iface = self.transport._iface  # kept for node listing (Stories 11.2, 11.3)
```

Connection status display (`self.iface.myInfo`, `self.iface.nodes`) is unchanged. The `self.iface` alias preserves all existing node listing code without modification.

### Step 3: Replace `_send_transaction_thread()`

Remove `PrintCapture`, `QueueLogHandler` setup, `cli_main()` call.

Replace with:
```python
def _send_transaction_thread(self, dest, tx_hex):
    sender = TransactionSender(self.transport)
    self._active_sender = sender

    def on_chunk_sending(chunk_num, total, attempt, wire_format):
        self.result_queue.put(('chunk_sending', chunk_num, total, attempt))
        self.result_queue.put(('wire_sent', wire_format))

    def on_progress(chunk_num, total):
        self.result_queue.put(('progress', chunk_num, total))

    def on_response_received(message_text):
        self.result_queue.put(('wire_received', message_text))

    result = sender.send_transaction(
        tx_hex, dest,
        on_progress=on_progress,
        on_chunk_sending=on_chunk_sending,
        on_response_received=on_response_received,
    )
    self.result_queue.put(('send_result', result))
```

Remove `dry_run` arg from thread (see Preview Mode section below for how dry run is handled).

### Step 4: Update `on_abort_pressed()`

Replace `self.abort_requested = True` with:
```python
def on_abort_pressed(self, instance):
    if self._active_sender:
        self._active_sender.abort()
    self.result_queue.put(('log', 'Abort requested...', 'WARNING'))
```

Remove `abort_requested` flag.

### Step 5: Update `process_result()` for new result types

Add `('wire_sent', message)` and `('wire_received', message)` branches:
```python
elif result_type == 'wire_sent':
    return ResultAction(log_msg=(f'  → {data}', COLOR_MUTED))
elif result_type == 'wire_received':
    return ResultAction(log_msg=(f'  ← {data}', COLOR_MUTED))
```

Add `('chunk_sending', chunk_num, total, attempt)` branch:
```python
elif result_type == 'chunk_sending':
    chunk_num, total, attempt = data
    if attempt > 1:
        msg = f'Sending chunk {chunk_num}/{total} (retry {attempt - 1})...'
    else:
        msg = f'Sending chunk {chunk_num}/{total}...'
    return ResultAction(log_msg=(msg, COLOR_PRIMARY))
```

Add `('progress', chunk_num, total)` branch:
```python
elif result_type == 'progress':
    chunk_num, total = data
    if chunk_num == total:
        return ResultAction(log_msg=(f'Chunk {chunk_num}/{total} sent — waiting for broadcast...', COLOR_PRIMARY))
    return ResultAction(log_msg=(f'Chunk {chunk_num}/{total} sent', COLOR_PRIMARY))
```

Add `('send_result', SendResult)` branch:
```python
elif result_type == 'send_result':
    send_result = data
    if send_result.success:
        return ResultAction(show_success_popup=send_result.txid, stop_sending=True)
    elif send_result.error == "Aborted by user":
        return ResultAction(log_msg=('Transaction aborted by user', COLOR_WARNING), stop_sending=True)
    else:
        return ResultAction(log_msg=(f'Error: {send_result.error}', COLOR_ERROR), stop_sending=True)
```

Remove `('print', text)` and `('cli_finished', exit_code)` branches.

### Step 6: Remove CLI imports and clean up

Remove from `btcmesh_gui.py`:
```python
from btcmesh_cli import cli_main, EXAMPLE_RAW_TX
```

Import `EXAMPLE_RAW_TX` from `core.constants` (or define it locally if not already exported).

Add:
```python
from transport.meshtastic_serial import MeshtasticSerialTransport
from client.sender import TransactionSender, SendResult
```

Also remove: `QueueLogHandler` class, `AbortedException`, `abort_requested` flag, `PrintCapture` class.

**Small cleanup:** Delete `_get_own_node_id()` — it duplicates `meshtastic_utils.get_own_node_id()`. Replace its call sites with `get_own_node_id(self.iface)` (already imported from `core.meshtastic_utils`).

### Step 7: Update tests (`tests/test_btcmesh_gui.py`)

Remove:
- Tests that mock `cli_main` and verify stdout parsing
- Tests for `('print', text)` result type
- Tests for `('cli_finished', exit_code)` result type

Add:
- `('chunk_sending', 1, 3, 1)` → "Sending chunk 1/3..."
- `('chunk_sending', 2, 3, 2)` → "Sending chunk 2/3 (retry 1)..."
- `('progress', 2, 3)` → "Chunk 2/3 sent"
- `('progress', 3, 3)` → "Chunk 3/3 sent — waiting for broadcast..."
- `('wire_sent', 'BTC_TX|...')` → "  → BTC_TX|..." with COLOR_MUTED
- `('wire_received', 'BTC_CHUNK_ACK|...')` → "  ← BTC_CHUNK_ACK|..." with COLOR_MUTED
- `('send_result', SendResult(success=True, txid='abc'))` → success popup
- `('send_result', SendResult(success=False, error='Insufficient fee'))` → error log
- `('send_result', SendResult(success=False, error='Aborted by user'))` → abort log

Unchanged:
- `validate_send_inputs()` tests
- Connection and node listing tests
- Success popup tests

---

## Preview Mode (Dry Run)

Dry run is a valid GUI feature: show how the transaction would be chunked before sending. In the new architecture it calls `core/protocol.create_session()` directly — no transport, no sender needed.

```python
def _run_preview(self, tx_hex):
    from core.protocol import create_session, get_chunk_message
    session = create_session(tx_hex)
    self.result_queue.put(('log', f'Preview: {session.total_chunks} chunk(s)', COLOR_PRIMARY))
    for i in range(session.total_chunks):
        msg = get_chunk_message(session, i)
        wire = msg.format()
        self.result_queue.put(('log', f'  Chunk {i+1}/{session.total_chunks}: {wire[:60]}...', COLOR_MUTED))
    self.result_queue.put(('send_result', SendResult(
        success=False,
        session_id=session.session_id,
        error='Preview only — not sent'
    )))
```

Called from `on_send_pressed()` when dry run toggle is active, instead of starting the send thread.

---

## Critical Files

| File | Change |
|------|--------|
| `client/sender.py` | Add `on_chunk_sending`, `on_response_received` callbacks; add `abort()` method |
| `btcmesh_gui.py` | Replace `cli_main` with `TransactionSender`; remove CLI-coupling artifacts |
| `tests/test_btcmesh_gui.py` | Update send-path tests; validation/UI tests unchanged |

---

## Key Design Decisions

### 1. Always-verbose wire messages
Currently the GUI logger is hardcoded to `logging.DEBUG`, so all protocol messages always appear. The new design preserves this: `on_chunk_sending` and `on_response_received` always fire. A user-facing verbose toggle is a future story.

### 2. `self.iface = self.transport._iface` (temporary tech debt)
`MeshtasticSerialTransport` does not expose `interface.nodes` or the raw iface object. Node listing (Stories 11.2, 11.3) still needs `self.iface.nodes`. Keeping `self.iface = self.transport._iface` avoids a larger change to the transport layer. This will be cleaned up when `MeshtasticSerialTransport` gets proper node enumeration support.

### 3. `on_response_received` as instance variable
Storing it as `self._on_response_received` (set at start of `send_transaction()`, cleared in `finally`) avoids threading through the parameter to `_on_message()`, which is a transport callback not under our control during the call chain.

### 4. Abort mechanism: threading.Event over flag
The current `abort_requested` boolean flag is checked inside `PrintCapture.write()` — it works by interrupting stdout writes mid-CLI-call. The new `_abort_event` is checked cleanly between chunks. More precise, easier to reason about, no stdout hijacking required.

### 5. `EXAMPLE_RAW_TX` location
Story 22.1 created `client/sender.py` which imports from `core.protocol`. Check whether `EXAMPLE_RAW_TX` was moved to `core.constants` during that story; if not, define it locally in `btcmesh_gui.py` rather than importing from `btcmesh_cli`.

---

## Verification

1. Run existing tests: `python -m unittest discover -s tests -p 'test_*.py'`
2. Manually launch GUI: `python btcmesh_gui.py`
   - Verify device connection and node listing still work
   - Verify send flow shows chunk-by-chunk progress including wire messages
   - Verify abort button stops the send
   - Verify success popup appears with TXID
   - Verify dry run shows preview without sending
3. Confirm `cli_main` is no longer imported in `btcmesh_gui.py`
4. Confirm `btcmesh_cli.py` is still intact and unchanged (removed in Story 22.3)
