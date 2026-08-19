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

**Revised after review** - the first draft below wired `record_failure()`
at the low transport level (`on_transport_error`, inside `_send()`) but
`record_success()` at a high, protocol-specific level (`on_chunk_received`,
only one of several things that call `_send()`). That's an asymmetry, not
just a style choice: `on_transport_error` already fires for *any* failed
reply send regardless of what was being sent (chunk-ack, NACK, final
ACK), so `record_success()` needs the same breadth - otherwise a
successful NACK or final-ACK send (equally strong proof the device is
alive) doesn't reset the failure counter, and an unlucky mix of a few
real-but-unrelated failures interleaved with successful non-chunk sends
could trip recovery even though the device just demonstrably worked.

**Fix**: add `on_transport_success` to `TransactionReceiver`
(`server/receiver.py`), firing at the exact same point `on_wire_sent`
already does - right after `self.transport.send(...)` succeeds inside
`_send()` - so every successful reply of any kind counts, symmetric with
`on_transport_error`. This also fixes the identical gap in the
already-merged CLI wiring (Story 26.5), which has the same asymmetry,
not just the GUI:

```python
# server/receiver.py - _send()
def _send(self, message: str, sender_id: str) -> None:
    try:
        self.transport.send(message, sender_id)
    except Exception as e:
        if self._on_transport_error:
            self._on_transport_error(e)
        raise
    if self._on_transport_success:
        self._on_transport_success()
    if self._on_wire_sent:
        self._on_wire_sent(message)
```

```python
receiver = TransactionReceiver(
    transport,
    rpc_client,
    reassembler=TransactionReassembler(timeout_seconds=reassembly_timeout),
    on_chunk_received=on_chunk_received,       # no longer touches the watchdog
    on_broadcast_started=on_broadcast_started,
    on_broadcast=on_broadcast,
    on_error=on_error,
    on_wire_sent=on_wire_sent,
    on_wire_received=on_wire_received,
    on_transport_error=lambda e: watchdog.record_failure(),
    on_transport_success=lambda: watchdog.record_success(),
)
```

`on_chunk_received` goes back to being purely a display/logging callback -
`record_success()` is removed from it entirely, since `on_transport_success`
now covers that case (and every other successful reply) at the source.

This keeps the watchdog's signal purely about local transport health -
never about chunk-protocol validity or remote-peer ACKs - exactly the
principle raised in review, just enforced consistently on both the
success and failure side instead of only the failure side.

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
| `server/receiver.py` | Add `on_transport_success` callback, fired in `_send()` symmetric with `on_transport_error` |
| `btcmesh_server_cli.py` | Fix the same asymmetry in the already-merged Story 26.5 wiring: move `record_success()` from `on_chunk_received` to `on_transport_success` |
| `btcmesh_server_gui.py` | `build_device_watchdog()` wiring, `on_transport_error`/`on_transport_success`, `watchdog.tick()` in the loop |
| `core/device_watchdog.py` | Reuse shared factory and callback behavior already implemented for CLI/server recovery (no changes needed) |
| `tests/test_server_receiver.py` | Test `on_transport_success` fires on a successful send, not on a failed one |
| `tests/test_btcmesh_server_cli.py` | Update existing Story 26.5 tests for the moved `record_success()` wiring |
| `tests/test_btcmesh_server_gui.py` | GUI watchdog tests for recovery attempt, recovered, failed, and the corrected success/failure wiring |
| `project/tasks.txt` | Mark Story 28.3 complete after verification |

---

## Key Design Decisions

1. **Follow the CLI pattern, but queue logs into the GUI** - the recovery logic is
   shared, but the GUI's UI thread must never be touched from the background server
   thread directly.
2. **Use the same watchdog factory already built for the CLI** - no duplicated
   recovery logic or config parsing in the GUI.
3. **`record_success()`/`record_failure()` reflect local transport health only,
   symmetrically, at the same low level** - never chunk-protocol validity, never
   remote-peer ACK receipt. `on_transport_error` already worked this way; `on_transport_success`
   (new) brings `record_success()` in line with it, firing on *every* successful
   reply send (chunk-ack, NACK, or final ACK alike) rather than only one narrow
   protocol path. This fixes a real asymmetry found in review - see "Wiring the
   receiver callbacks" above - present in both the CLI (already merged) and the
   original draft of this story.
4. **No separate watchdog background thread for the GUI** - the GUI already runs a
   loop; `watchdog.tick(now)` belongs in that same loop, keeping the behavior simple
   and consistent with the rest of the server runtime.

---

## Implementation Progress

**Done.** All items implemented and tested.

- [x] Wire the shared `build_device_watchdog()` factory into the GUI server
      startup path
- [x] Wire `on_transport_error` into the GUI's `TransactionReceiver` construction
- [x] Add `watchdog.tick(now)` in the GUI loop alongside the existing
      timeout and heartbeat checks
- [x] Add `on_transport_success` to `TransactionReceiver`/`_send()` (`server/receiver.py`)
- [x] Fix the CLI's Story 26.5 wiring to use `on_transport_success` instead of
      calling `record_success()` from `on_chunk_received`
- [x] Fix the GUI wiring the same way (removed `record_success()` from
      `on_chunk_received`, wired `on_transport_success` instead)
- [x] Update/add tests across all three affected files:
      `tests/test_server_receiver.py::TestTransactionReceiverTransportSuccess`
      (3 tests, including a NACK-send case proving the signal isn't tied
      to chunk validity), `tests/test_btcmesh_server_cli.py::TestBuildReceiver`
      (updated), `tests/test_btcmesh_server_gui.py::TestServerDeviceWatchdogStory283`
      (updated). Full suite: 724 tests passing.

---

## Verification

- **Unit tests**:
  - `on_transport_success` fires exactly when `_send()` succeeds, never when it
    raises (and `on_transport_error` fires exactly the reverse).
  - CLI: `record_success()` is called via `on_transport_success`, not
    `on_chunk_received`, for all three reply-send call sites (chunk-ack, NACK,
    final ACK).
  - GUI: same coverage as the CLI, plus the existing recovery-attempt/recovered/failed
    and `watchdog.tick()`-per-iteration checks.
  - GUI loop still emits the liveness log (Story 28.2) at the configured interval.
  - Recovery-event logs are routed through the GUI's `result_queue` rather than
    touching widgets directly from the background thread.
- **Regression check**: full suite still passes.
