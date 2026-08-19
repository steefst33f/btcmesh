# Story 28.3 Implementation Plan: Wire DeviceWatchdog into the server GUI

## Context

**Why this change:**
Story 28.2 added a periodic positive signal so the server stays observable during
idle times, but it does not close the actual resilience gap. The overnight field
issue showed the live production path was the GUI server, not the CLI, and the
GUI was still missing the watchdog wiring that Story 26.5 had already added to
`btcmesh_server_cli.py`.

**The root problem:**
The GUI server loop runs on a background thread and already tracks session timeouts,
but it has no watchdog-driven detection or recovery path. A wedged Meshtastic
transport can therefore sit unmonitored for long periods, even though the CLI and
GUI share the same underlying transport and recovery logic.

**Scope decision:**
This story follows the same pattern as the CLI wiring but adapts it to the GUI's
thread-safe queue model: results are sent over `result_queue`, while the actual
watchdog logic remains in `core/device_watchdog.py` with the same callback design
already used elsewhere.

**Goal:**
Stop the server GUI from silently drifting into a wedged, unresponsive state by
hooking `DeviceWatchdog` into the live GUI loop and reporting life-cycle events
through the same UI log pipeline the server GUI already uses.

---

## Design

### Shared watchdog setup

The GUI already has the right abstraction pattern for background work: it uses a
`result_queue` and `_process_results()` to deliver results back onto the Kivy main
thread. The watchdog setup should follow the same pattern:

```python
watchdog, power_control = build_device_watchdog(
    transport,
    on_recovery_attempt=lambda: self.result_queue.put((
        'log',
        'Device appears wedged - attempting automatic recovery...',
        logging.WARNING,
    )),
    on_recovered=lambda outcome: self.result_queue.put((
        'log',
        f"Device recovered. Reconnected at {outcome.new_device_path}.",
        logging.INFO,
    )),
    on_recovery_failed=lambda outcome: self.result_queue.put((
        'log',
        f"Automatic device recovery failed: {outcome.error}",
        logging.ERROR,
    )),
)
```

This preserves the no-duplicated-logic principle: the watchdog is still created
by a shared factory in `core/device_watchdog.py`, and the GUI only supplies the
UI-specific callback bodies.

### Wiring the receiver callbacks

The constructor for `TransactionReceiver` gets the watchdog callback:

```python
receiver = TransactionReceiver(
    transport,
    rpc_client,
    reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
    on_chunk_received=on_chunk_received,
    on_broadcast_started=on_broadcast_started,
    on_broadcast=on_broadcast,
    on_error=on_error,
    on_wire_sent=on_wire_sent,
    on_wire_received=on_wire_received,
    on_transport_error=lambda e: watchdog.record_failure(),
)
```

The chunk-received callback adds one extra signal after a chunk is successfully
processed by the local transport path. That is a transport-health signal, but it
must not be mistaken for a remote peer ACK check:

```python
def on_chunk_received(evt: ChunkReceived):
    self.result_queue.put((
        'log',
        f"[{evt.session_id}] Received chunk {evt.chunk_num}/{evt.total_chunks} from {evt.sender_id}",
        logging.INFO,
        COLOR_PRIMARY,
    ))
    # ... existing log lines ...
    watchdog.record_success()
```

This is intentionally narrower than "ACK received from a peer." A missing ACK can
mean no other node is reachable, but it does not prove that the local Meshtastic
radio/device is wedged or powered off. The watchdog should therefore reset on
successful local transport health evidence (for example: a successful send/receive
operation or explicit liveness check), not on the absence of a remote ACK.

### Main loop updates

The GUI server loop already performs periodic cleanup and heartbeats. It should
expand to include the watchdog tick in the same cadence as the CLI:

```python
last_cleanup_time = time.time()
last_liveness_log = time.time()
while not self._stop_event.is_set():
    active_sessions = receiver.get_active_sessions()
    self.result_queue.put(('active_sessions', active_sessions))

    now = time.time()
    if now - last_cleanup_time >= CHECK_TIMEOUTS_INTERVAL_SECONDS:
        receiver.check_timeouts()
        last_cleanup_time = now

    if now - last_liveness_log >= LIVENESS_LOG_INTERVAL_SECONDS:
        self.result_queue.put((
            'log',
            f"Server heartbeat: alive, listening. {len(active_sessions)} active session(s).",
            logging.INFO,
        ))
        last_liveness_log = now

    watchdog.tick(now)
    time.sleep(1)
```

This preserves the current server GUI behavior while adding the missing real-world
recovery checks.

---

## Critical Files

| File | Change |
|------|--------|
| `btcmesh_server_gui.py` | Add `build_device_watchdog()` wiring, `on_transport_error`, `record_success()`, and `watchdog.tick()` in the loop |
| `core/device_watchdog.py` | Reuse shared factory and callback behavior already implemented for CLI/server recovery |
| `server/receiver.py` | Ensure the callback hook is reached when a transport send fails, so the watchdog can react |
| `tests/test_btcmesh_server_gui.py` | GUI watchdog tests for recovery attempt, recovered, and failed paths |
| `project/tasks.txt` | Mark Story 28.3 complete after verification |

---

## Key Design Decisions

1. **Follow the CLI pattern, but queue logs into the GUI** - the recovery logic is
   shared, but the GUI's UI thread must never be touched from the background server
   thread directly.
2. **Use the same watchdog factory already built for the CLI** - no duplicated
   recovery logic or config parsing in the GUI.
3. **Reset on local transport health evidence, not on remote peer ACK absence** - a
   missing ACK is not the same thing as a wedged Meshtastic device. The watchdog
   should treat current device responsiveness as the signal, using successful local
   transport operations or explicit liveness checks as the health indicator.
4. **No separate watchdog background thread for the GUI** - the GUI already runs a
   loop; `watchdog.tick(now)` belongs in that same loop, keeping the behavior simple
   and consistent with the rest of the server runtime.

---

## Implementation Progress

- **Planned**: wire the shared `build_device_watchdog()` factory into the GUI server
  startup path.
- **Planned**: add the watchdog callback to `TransactionReceiver` in the GUI's
  `run_server()` closure.
- **Planned**: add `watchdog.record_success()` to the chunk-received flow.
- **Planned**: add `watchdog.tick(now)` in the GUI loop alongside the existing
  timeout and heartbeat checks.

---

## Verification

The implementation should be validated with the existing GUI/server regression tests,
plus a targeted watchdog check in:

- `tests/test_btcmesh_server_gui.py`

The expected checks are:
- watchdog callback fires on transport failure;
- successful chunk processing resets the failure count;
- the GUI loop still emits the liveness log at the longer interval;
- recovery-event logs are routed through the GUI result queue rather than direct
  UI mutation from the background thread.
