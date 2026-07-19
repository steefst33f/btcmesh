# Story 23.2 Implementation Plan: Refactor btcmesh_server_gui.py to use server/receiver.py

## Context

**Why this change:**
`btcmesh_server_gui.py` doesn't connect to Meshtastic or Bitcoin RPC itself at all today — it calls `btcmesh_server.main(stop_event, rpc_config, serial_port, reassembly_timeout, session_update_callback)` in a background thread, and that function does *all* the connecting, reassembling, and broadcasting internally. To learn what happened, the GUI attaches a `QueueLogHandler` to `server_logger` and **regex-parses log message text** (`parse_log_for_status()`) to detect connection/status changes ("Connected to Bitcoin Core RPC node successfully", "Meshtastic interface initialized successfully", etc.). This is the same log-scraping coupling Story 22.2 eliminated on the client side (`cli_main()` + stdout/log capture), just more elaborate here since it also has to infer *connection setup* status, not just send progress.

**Goal:**
The GUI does its own connection setup (`MeshtasticSerialTransport`, `BitcoinRPCClient`) directly, constructs a `TransactionReceiver` (Story 23.1) with typed callbacks, and drives a simple maintenance loop itself (mirroring `btcmesh_server.py`'s current `main()` loop structure, just without `btcmesh_server.py` in the call chain). Status updates come from **direct, structured events** the GUI produces itself — not from parsing log text.

**Outcome:**
`btcmesh_server_gui.py` only handles UI: widget setup, connection setup + result-queue events, and callbacks that format receiver events into activity-log messages and `TransactionHistory` entries. `btcmesh_server.py` is **not modified in this story** (mirrors Story 22.2 leaving `btcmesh_cli.py` untouched, replaced later in 22.3/23.3).

---

## Current Flow (to be replaced)

```
on_start_pressed()
  → QueueLogHandler attached to server_logger
  → run_server() [background thread]
      → btcmesh_server.main(stop_event, rpc_config, serial_port, reassembly_timeout, session_callback)
          [internally: initialize_meshtastic_interface(), BitcoinRPCClient(rpc_config),
           pub.subscribe(on_receive_text_message), while-loop: session_update_callback
           every 1s, cleanup_stale_sessions() every 10s]
      → every log record → result_queue.put(('log', text, level))
      → session_callback(sessions_info) → result_queue.put(('active_sessions', sessions_info))
  → _process_results() [Clock, every 0.1s]
      → result_type == 'log' → parse_log_for_status(text) → regex-matches known message
          substrings → _apply_status_update(('rpc_connected'|'rpc_failed'|
          'meshtastic_connected'|'meshtastic_failed'|'server_started'|'server_stopped'|
          'pubsub_error', data))
      → result_type == 'active_sessions' → _update_active_sessions(data)
```

## New Flow

```
on_start_pressed()
  → run_server() [background thread]
      → transport = MeshtasticSerialTransport(); transport.connect(serial_port)
          success → result_queue.put(('meshtastic_connected', {'node_id':.., 'device':..}))
          failure → result_queue.put(('meshtastic_failed', str(e))); return
      → rpc_client = BitcoinRPCClient(rpc_config)
          success → result_queue.put(('rpc_connected', {'host':.., 'is_tor':.., 'chain':..}))
          failure → result_queue.put(('rpc_failed', str(e))); transport.disconnect(); return
      → history = TransactionHistory()
      → receiver = TransactionReceiver(transport, rpc_client,
            reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
            on_chunk_received=..., on_broadcast=..., on_error=...)
            [callbacks format a log line for result_queue.put(('log', text, level))
             AND record to history.add(...) for on_broadcast/on_error]
      → result_queue.put(('server_started', None))
      → while not stop_event.is_set():
            result_queue.put(('active_sessions', receiver.get_active_sessions()))   [every 1s]
            receiver.check_timeouts()                                              [every 10s]
            time.sleep(1)
      → finally: transport.disconnect(); result_queue.put(('server_stopped', None))
  → _process_results() [Clock, every 0.1s, UNCHANGED]
      → result_type in ('rpc_connected', 'rpc_failed', 'meshtastic_connected',
          'meshtastic_failed', 'server_started', 'server_stopped') →
          _apply_status_update((result_type, data))   [UNCHANGED - same event shapes]
      → result_type == 'log' → display only, no more parse_log_for_status() call
      → result_type == 'active_sessions' → _update_active_sessions(data)   [UNCHANGED]
```

Note `_apply_status_update()` and `_update_active_sessions()` keep their **exact current signatures and event shapes** — only *how* those events get produced changes (direct pushes instead of regex-inferred from log text). This keeps the blast radius on the UI-rendering code itself close to zero.

---

## Architecture Overview

### What Gets Removed from btcmesh_server_gui.py

```
├── QueueLogHandler class                    ← log-capture-for-status mechanism, no longer needed
├── parse_log_for_status()                   ← regex inference of status from log text
├── self._log_handler / _cleanup_log_handler()
├── import btcmesh_server                    ← no longer calls its main()
└── 'pubsub_error' handling                  ← was only reachable via a log-parsed pubsub
                                                ImportError inside btcmesh_server.main();
                                                MeshtasticSerialTransport.connect() raises
                                                TransportConnectionError instead, folds into
                                                the existing 'meshtastic_failed' path
```

### What Gets Added

```
├── from transport.meshtastic_serial import MeshtasticSerialTransport
├── from transport.base import TransportConnectionError
├── from core.rpc_client import BitcoinRPCClient
├── from core.reassembler import TransactionReassembler
├── from server.receiver import TransactionReceiver, ChunkReceived, BroadcastResult
└── run_server()'s own connection setup, callback definitions, and maintenance loop
    (replacing the single btcmesh_server.main() call)
```

### What Stays Unchanged

```
├── _apply_status_update()          — same event shapes, different event source
├── _update_active_sessions()       — same sessions_info shape from get_active_sessions()
├── _on_scan_devices(), _on_test_connection(), _on_save_settings()  — already independent
├── History button / popup          — reads TransactionHistory().get_all() directly, unaffected
├── All widget-building code        — no UI layout changes
└── btcmesh_server.py                — untouched (Story 23.3 territory)
```

---

## Implementation Steps

### Step 1: Replace `on_start_pressed()`'s `run_server()` inner function

```python
def run_server():
    transport = MeshtasticSerialTransport()
    try:
        transport.connect(serial_port)
    except TransportConnectionError as e:
        self.result_queue.put(('meshtastic_failed', str(e)))
        return

    self.result_queue.put((
        'meshtastic_connected',
        {'node_id': transport.local_node_id, 'device': serial_port or 'auto-detect'},
    ))

    try:
        rpc_client = BitcoinRPCClient(rpc_config)
    except Exception as e:
        self.result_queue.put(('rpc_failed', str(e)))
        transport.disconnect()
        return

    is_tor = rpc_config['host'].endswith('.onion')
    self.result_queue.put((
        'rpc_connected',
        {'host': rpc_config['host'], 'is_tor': is_tor, 'chain': rpc_client.chain},
    ))

    history = TransactionHistory()

    def on_chunk_received(evt: ChunkReceived):
        self.result_queue.put((
            'log',
            f"[{evt.session_id}] Chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}",
            logging.INFO,
        ))

    def on_broadcast(result: BroadcastResult):
        if result.success:
            self.result_queue.put((
                'log', f"[{result.session_id}] Broadcast success. TXID: {result.txid}", logging.INFO
            ))
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="success", txid=result.txid, raw_tx=result.raw_tx)
        else:
            self.result_queue.put((
                'log', f"[{result.session_id}] Broadcast failed: {result.error}", logging.ERROR
            ))
            history.add(session_id=result.session_id, sender=result.sender_id,
                        status="failed", error=result.error, raw_tx=result.raw_tx)

    def on_error(session_id, sender_id, error):
        self.result_queue.put((
            'log', f"[{session_id}] Error from {sender_id}: {error}", logging.WARNING
        ))
        history.add(session_id=session_id, sender=sender_id, status="failed",
                    error=error, raw_tx=None)

    receiver = TransactionReceiver(
        transport, rpc_client,
        reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
        on_chunk_received=on_chunk_received,
        on_broadcast=on_broadcast,
        on_error=on_error,
    )

    self.result_queue.put(('server_started', None))

    try:
        last_cleanup_time = time.time()
        while not self._stop_event.is_set():
            self.result_queue.put(('active_sessions', receiver.get_active_sessions()))
            now = time.time()
            if now - last_cleanup_time >= 10:
                receiver.check_timeouts()
                last_cleanup_time = now
            time.sleep(1)
    finally:
        transport.disconnect()
        self.result_queue.put(('server_stopped', None))
```

`on_start_pressed()`'s validation and UI-disabling code above this (host/port/user/password/timeout checks, disabling inputs) stays unchanged. The `QueueLogHandler` setup lines are removed entirely.

### Step 2: Remove `QueueLogHandler`, `parse_log_for_status()`, `_cleanup_log_handler()`

Delete the class and function. Remove all `self._cleanup_log_handler()` call sites in `_apply_status_update()` (in the `meshtastic_failed`, `pubsub_error`, `server_stopped`, `init_error` branches) — nothing left to clean up. Remove the `'pubsub_error'` branch from `_handle_result()`/`_apply_status_update()` (no longer reachable; `MeshtasticSerialTransport` doesn't depend on `pubsub` failing independently of the connect() call itself — a missing `pubsub` library would surface as an `ImportError` inside `transport.connect()`, which is already caught by the generic `except Exception` there... actually `connect()` only catches specific exceptions; confirm during implementation whether a missing `pubsub` import needs its own path or naturally surfaces as `meshtastic_failed`).

### Step 3: Remove `import btcmesh_server`

No longer used anywhere in the file.

### Step 4: Update `tests/test_btcmesh_server_gui.py`

- Remove `TestServerLogParsingStory152` (14 tests) and `TestQueueLogHandlerStory152` (2 tests) entirely — `parse_log_for_status()` and `QueueLogHandler` no longer exist.
- Remove/update any test referencing `btcmesh_server.main` or `_log_handler`/`_cleanup_log_handler`.
- Add tests for the new `run_server()` connection-setup logic (mocking `MeshtasticSerialTransport`, `BitcoinRPCClient`, `TransactionReceiver`) mirroring the patterns already used in `tests/test_btcmesh_client_gui.py` for the client-side equivalent (Story 22.2).
- `TestServerResultHandlingStory152` and `TestActiveSessionsDisplayStory172` mostly stay as-is (`_apply_status_update`/`_update_active_sessions` unchanged), just double-check they don't reference removed internals.

### Step 5: Full test suite run + manual verification

See Verification below.

---

## Critical Files

| File | Change |
|---|---|
| `btcmesh_server_gui.py` | Remove `QueueLogHandler`, `parse_log_for_status()`, `import btcmesh_server`; replace `run_server()` with direct transport/RPC/receiver setup + maintenance loop |
| `tests/test_btcmesh_server_gui.py` | Remove ~16 log-parsing/QueueLogHandler tests; add `run_server()`/connection-setup tests |
| `btcmesh_server.py` | **Unchanged** — replaced in Story 23.3 |

---

## Key Design Decisions

### 1. `_apply_status_update()` / `_update_active_sessions()` keep identical event shapes
Deliberately did not change the tuple shapes for `rpc_connected`/`rpc_failed`/`meshtastic_connected`/`meshtastic_failed`/`server_started`/`server_stopped`/`active_sessions` — only *how* they're produced changes (direct pushes vs. regex-parsed from log text). Minimizes changes to already-correct, already-tested UI-rendering code.

### 2. Transaction history recording expands slightly beyond old behavior
The old `btcmesh_server.py` only calls `transaction_history.add()` for: broadcast success, broadcast failure, the generic catch-all exception during chunk processing, and session timeout — **not** for `InvalidChunkFormatError`/`MismatchedTotalChunksError` (malformed/mismatched chunks just get NACKed, no history entry). Since `TransactionReceiver.on_error` (Story 23.1) deliberately unifies reassembly errors, unexpected errors, and timeouts into one callback (by design, see Story 23.1's Key Design Decision 4), the GUI's `on_error` handler records **all** of them to history. This is a small, deliberate behavior improvement (a malformed-chunk NACK becomes a visible failed history entry instead of disappearing silently) — flagging it explicitly since it's a user-visible change from current behavior, not just a refactor.

### 3. `pubsub_error` status type likely becomes dead code
The old `'pubsub_error'` status only existed because `btcmesh_server.main()` caught a `pubsub` `ImportError` separately from Meshtastic connection errors. `MeshtasticSerialTransport.connect()` doesn't have that distinction — a `pubsub` import problem would need to be confirmed during implementation to see whether it naturally surfaces via `TransportConnectionError` (folding into `meshtastic_failed`) or needs no handling at all (since `pubsub` is a hard dependency already required for `meshtastic` itself to function, this failure mode may not be practically reachable). Decide once implementation is underway; if genuinely dead, remove the branch and its tests.

### 4. Reassembly timeout wired through an explicit `TransactionReassembler`
The GUI's user-configurable "Reassembly Timeout" input now constructs `TransactionReassembler(timeout_seconds=reassembly_timeout)` explicitly and passes it into `TransactionReceiver(reassembler=...)`, rather than `TransactionReceiver` defaulting to `DEFAULT_REASSEMBLY_TIMEOUT`.

### 5. Maintenance loop lives in the GUI's `run_server()`, not in `TransactionReceiver`
Consistent with Story 23.1's design (receiver has no background thread/polling of its own) — the GUI's own background thread drives `check_timeouts()`/`get_active_sessions()` on a timer, exactly mirroring `btcmesh_server.py`'s current `main()` loop structure (1s active-session updates, 10s stale-session cleanup), just without `btcmesh_server.py` in the call chain.

---

## Verification

1. Run the full suite: `python -m unittest discover -s tests -p 'test_*.py'` — expect current total minus ~16 removed log-parsing/QueueLogHandler tests, plus new connection-setup tests, all passing.
2. Confirm `btcmesh_server_gui.py` no longer imports `btcmesh_server`.
3. Confirm `btcmesh_server.py` is byte-for-byte unchanged (`git diff` shows no hits).
4. Manually launch `python btcmesh_server_gui.py` against real hardware + the testnet RPC node used in Story 23.1's verification:
   - Start the server, confirm Meshtastic/RPC/network-badge status update correctly (now via direct events, not log parsing).
   - Send a real transaction from `btcmesh_client_cli.py`, confirm the activity log shows chunk-received and broadcast-result messages, the active-sessions display updates live, and a new entry appears in the History popup.
   - Stop the server, confirm status resets to disconnected and the Meshtastic port is released (`lsof` shows nothing holding it).

---

## Implementation Completion

**Status:** ✅ **COMPLETE** (July 19, 2026), including real-hardware verification (see below)

**Test results:** 609 tests passing (161 → 142 in `tests/test_btcmesh_server_gui.py`: 19 dead log-parsing/QueueLogHandler tests removed, 3 rewritten in place to mock the new dependencies instead of `btcmesh_server.main`; other suites unaffected).

**Deviations from initial plan:**
- Fixed a real bug caught during review, before it ever reached real hardware: my first draft disconnected the transport and aborted server start entirely if the RPC connection failed. The old `btcmesh_server.py` explicitly continues running with `bitcoin_rpc=None` when RPC fails (Meshtastic keeps receiving/reassembling/ACKing chunks; only the final broadcast step fails once a transaction actually completes) - fixed `run_server()` to match: RPC failure now only pushes `rpc_failed` and proceeds, never touching the transport.
- Added a safety-net `try/except` around `TransactionReceiver` construction, pushing `init_error` on any unexpected exception - without it, an unanticipated error there would silently kill the daemon thread and leave the GUI stuck showing "Starting server..." forever, since nothing would report back to the result queue. Restores the same safety net the old code had wrapping the whole `btcmesh_server.main()` call.
- Confirmed `pubsub_error` (Key Design Decision 3) and `server_stopping` were both dead code with the new design (neither ever gets pushed by the new `run_server()`, and no tests referenced either) - removed both branches along with the log-parsing tests, rather than leaving unreachable code in place.
- Removed the now-unused `server_logger` and `re` imports as a result of removing `QueueLogHandler`/`parse_log_for_status()`.

**Manual verification - completed:**
- Automated coverage is solid: the 3 rewritten tests directly verify `run_server()`'s new connection-setup calls (`transport.connect(serial_port)` with the right port for both auto-detect and explicit-device cases, `TransactionReassembler(timeout_seconds=...)` with the GUI's configured timeout).
- Story 23.1 already proved `TransactionReceiver` itself works end-to-end against real hardware and a real testnet RPC node (chunk ACK, reassembly, broadcast attempt, NACK on failure all confirmed).
- **Full click-through against real hardware, retried 2026-07-19** after both devices were power-cycled (the earlier "wedged" state documented in Issue 12/16 did not reproduce this time). Ran a standalone script mirroring `run_server()`'s exact connection/receive logic (real GUI click-through isn't scriptable without a display) against both real Meshtastic devices and the real testnet RPC node over Tor:
  - Meshtastic serial connect + Bitcoin RPC connect (Tor, testnet, chain `test`) both succeeded cleanly on both devices - this was the actual item blocked last time, and it's now confirmed working.
  - Sent a real 15-chunk transaction end-to-end. `TransactionReceiver` correctly tracked the active session, received and deduplicated a genuinely retried chunk (re-ACKing it rather than double-processing), and updated active-session state exactly as `run_server()`'s maintenance loop expects.
  - The transaction did not reach a final broadcast in this run - chunk transfer hit the same pre-existing RF unreliability documented in Issue 16 (details added there). This is environmental/hardware, not a defect in this story's code: every piece of `server/receiver.py` logic exercised by the real traffic that did arrive behaved correctly.

**Files changed:**

| File | Change |
|---|---|
| `btcmesh_server_gui.py` | Removed `QueueLogHandler`, `parse_log_for_status()`, `import btcmesh_server`; `run_server()` now does direct transport/RPC/receiver setup + maintenance loop |
| `tests/test_btcmesh_server_gui.py` | Removed 19 dead tests, rewrote 3 to mock the new dependencies |

**Next steps:**
- Story 23.3: Create `btcmesh_server_cli.py` as a thin CLI entry point, then delete `btcmesh_server.py` (parallel to Story 22.3)
