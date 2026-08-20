# Story 28.2 Implementation Plan: Periodic "still alive" logging for both server entry points

## Context

**Why this change:**
Running the relay server overnight surfaced an observability gap, not just a
recovery gap: when nothing was happening, there was no positive signal that the
process was still alive. If a wedged server simply stopped logging, the operator
had no way to distinguish "it's still working and quiet" from "it silently died
or hung". This is especially relevant to Issue 21, because the downstream
recovery work (watchdog, timeout, and detection) all assume a process can be
checked from its logs even when no traffic is arriving.

**Root cause:**
Both server entry points (`btcmesh_server_cli.py` and `btcmesh_server_gui.py`)
run a `while ...` loop with periodic cleanup work, but there was no "heartbeat"
log at a longer cadence. The existing activity in the log depended entirely on
incoming traffic or changes in session state; during idle periods, the server
could appear totally dead even while still running.

**What this story fixes:**
Add a periodic INFO log line when the server has been running for a while with no
other activity, so the operator can confirm from the log alone that the process is
still listening, even when no new chunks arrive.

**Scope note:**
This story is intentionally narrow and implementation-focused: no watchdog logic,
no transport timeout changes, no automatic recovery. It is only the positive
"still alive" signal that makes overnight server health observable.

---

## Design

### `btcmesh_server_cli.py`

Add a constant and a second cadence check inside the server loop, alongside the
existing `check_timeouts()` loop:

```python
LIVENESS_LOG_INTERVAL_SECONDS = 300

last_cleanup = time.time()
last_liveness_log = time.time()
while True:
    now = time.time()
    if now - last_cleanup >= CHECK_TIMEOUTS_INTERVAL_SECONDS:
        receiver.check_timeouts()
        last_cleanup = now

    if now - last_liveness_log >= LIVENESS_LOG_INTERVAL_SECONDS:
        active = len(receiver.get_active_sessions())
        server_logger.info(
            f"Server heartbeat: alive, listening. {active} active session(s)."
        )
        last_liveness_log = now

    watchdog.tick(now)
    time.sleep(1)
```

This keeps the heartbeat independent from day-to-day traffic and does not require
incoming messages to produce a visible log entry.

### `btcmesh_server_gui.py`

The GUI uses the same pattern but routes the log entry through the existing
`result_queue` mechanism instead of calling `server_logger` directly, matching the
rest of the GUI's logger/reporting model:

```python
CHECK_TIMEOUTS_INTERVAL_SECONDS = 10

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

    time.sleep(1)
```

This preserves the same positive signal in GUI-backed operation while keeping the
UI loop thread-safe and aligned with the rest of the GUI logger pipeline.

---

## Critical Files

| File | Change |
|------|--------|
| `btcmesh_server_cli.py` | Add the CLI heartbeat log and liveness cadence |
| `btcmesh_server_gui.py` | Add the GUI heartbeat log and queue-based reporting |
| `tests/test_btcmesh_server_cli.py` | Add CLI heartbeat logging test |
| `tests/test_btcmesh_server_gui.py` | Add GUI heartbeat logging test |
| `project/tasks.txt` | Mark Story 28.2 complete once verified |

---

## Key Design Decisions

1. **Use a longer cadence than timeout checks** - `check_timeouts()` already runs
   every `CHECK_TIMEOUTS_INTERVAL_SECONDS`, while the liveness log is intentionally
   much slower (5 minutes), so it acts as a positive signal without flooding the
   log during normal quiet periods.
2. **Keep it traffic-independent** - the heartbeat is based on wall-clock time,
   not activity count or incoming message events, so it remains reliable even when
   the server is otherwise idle.
3. **Match each UI style** - the CLI writes directly to `server_logger`, while the
   GUI writes via `result_queue` so the background server thread remains Kivy-safe
   and consistent with the rest of the UI messaging model.
4. **No new protocol or config surface** - this is a pure observability add-on and
   intentionally does not require any new env vars or user settings.

---

## Implementation Progress

- **Implemented in the CLI**: `btcmesh_server_cli.py` now logs a periodic heartbeat
  when the server is idle and running, with "Server heartbeat: alive, listening.
  X active session(s).".
- **Implemented in the GUI**: `btcmesh_server_gui.py` now emits the same heartbeat
  through the existing queue-driven log system.
- **Verified by tests**: both CLI and GUI tests assert the heartbeat message fires
  after the configured interval, and does not fire before the interval elapses.

---

## Verification

The behavior is covered by unit tests in:

- `tests/test_btcmesh_server_cli.py::TestRunServerLivenessLog`
- `tests/test_btcmesh_server_gui.py` (liveness log checks)

These tests confirm:
- the liveness log is emitted after the interval expires;
- the log does not fire before the interval expires;
- the server remains in its quiet-idle state without requiring any incoming traffic.

### Real-hardware verification (CLI)

Ran `btcmesh_server_cli.py` against a real connected Meshtastic device
(no mocking) and let it idle with no incoming traffic:

```
2026-08-20 02:09:58,100 - btcmesh_server - INFO - Server started. Listening for incoming transactions... (Ctrl+C to stop)
2026-08-20 02:14:58,702 - btcmesh_server - INFO - Server heartbeat: alive, listening. 0 active session(s).
```

The heartbeat fired at exactly the 5-minute (300s) mark from server
start, with no other activity needed to produce it - confirming the fix
against real hardware, not just mocked `time.time()`. GUI side not yet
verified against real hardware (same underlying loop logic, covered by
unit tests only so far).
