# Story 28.4 Implementation Plan: Detection-Only DeviceWatchdog for the Client GUI

## Context

**Why this change:**
Issue 21's root-cause investigation found that the client had no
`DeviceWatchdog` at all - Story 26.6 was explicitly decided against
(`project/plans/story_26_6.md`), reasoned around *automatic recovery*
requiring relay hardware most client machines won't have. That
reasoning still holds. But the overnight incident showed the gap this
left: with no liveness check running during idle time, a device that
wedged at some point overnight sat there completely undetected until
the first real send hung and eventually froze the whole application
(before Story 28.1's send-timeout fix).

**Why this is smaller than the original Story 26.6 scope**: what's
missing isn't automatic recovery - it's *detection*. `build_device_watchdog()`
already degrades gracefully to detect-only when no `RELAY_SERIAL_PORT`
is configured (`power_control=None`), so a heartbeat that only ever
reports "device unresponsive" (never attempts a power cycle) is a much
smaller addition than the original full-recovery scope, and would have
surfaced this exact overnight wedge - as an honest "please reconnect"
message - before the user ever tried to send into it.

**Design carried over unchanged from `project/plans/story_26_6.md`**
(that story's design work is reused here, not redone):
- **Dedicated background thread, not `Clock.schedule_interval`** -
  `tick()` can block (up to `check_alive()`'s ~20s timeout in
  detect-only mode, or a full multi-minute recovery cycle if a relay
  happens to be configured), and `Clock` callbacks run on Kivy's main
  thread - calling `tick()` there would freeze the whole window for
  that long.
- **Gated on `self._active_sender`** - skips ticking entirely while a
  send is in progress, so it never races an in-flight send for the
  transport (matches this story's "recovery for the next attempt, not
  racing the send" principle).
- **Results routed through `self.result_queue`** - `DeviceWatchdog`
  invokes callbacks from the background watchdog thread, and Kivy
  widgets must only be touched from the main thread; reuses the exact
  pattern already used for every other background operation (connect,
  send, disconnect).
- **`self.iface` explicitly refreshed on `on_recovered`** - `DeviceWatchdog`
  reconnects the same transport object, but `self.iface` is a separate
  raw-interface reference the GUI captured for node listing (Stories
  11.2/11.3) that goes stale across a reconnect unless refreshed.

**One addition beyond the original Story 26.6 draft**: since most
client users won't have a relay, `on_recovery_failed` firing because
`power_control is None` is the *normal*, expected outcome, not a
failure worth alarming language - the message distinguishes it from a
genuine failed recovery attempt with a relay actually present.

---

## Design

### New GUI state (`BTCMeshGUI.__init__`)

```python
self.watchdog = None
self.power_control = None
self._watchdog_thread = None
self._watchdog_running = False
```

### Building the watchdog, once a transport exists

In `_handle_result()`, right after the existing `'transport_ready'`
handling:

```python
if result[0] == 'transport_ready':
    self.transport = result[1]
    self.watchdog, self.power_control = build_device_watchdog(
        self.transport,
        on_recovery_attempt=lambda: self.result_queue.put(('watchdog_attempt',)),
        on_recovered=lambda outcome: self.result_queue.put(('watchdog_recovered', outcome)),
        on_recovery_failed=lambda outcome: self.result_queue.put(('watchdog_failed', outcome)),
    )
    self._start_watchdog_thread()
    return
```

### The watchdog thread itself

```python
def _start_watchdog_thread(self):
    self._watchdog_running = True

    def watchdog_loop():
        while self._watchdog_running:
            if self.watchdog is not None and self._active_sender is None:
                self.watchdog.tick(time.time())
            time.sleep(1)

    self._watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
    self._watchdog_thread.start()
```

`tick()` already internally no-ops unless `heartbeat_interval_seconds`
has elapsed, so calling it every second here is cheap in the common
case - matching the exact polling cadence the server's own main loop
already uses.

### Stopping it

`_disconnect_device()` gains, at the top:

```python
self._watchdog_running = False
self.watchdog = None
self.power_control = None
```

`BTCMeshApp.on_stop()` also sets `self.root._watchdog_running = False`
alongside its existing `iface.close()` cleanup, so the daemon thread
doesn't keep ticking after app close (harmless either way since it's a
daemon thread, but tidy).

### Handling watchdog results in `_handle_result()`

```python
if result[0] == 'watchdog_attempt':
    self.status_log.add_message(
        "Device appears wedged - attempting automatic recovery...", COLOR_WARNING
    )
    return

if result[0] == 'watchdog_recovered':
    outcome = result[1]
    self.status_log.add_message(
        f"Device recovered. Reconnected at {outcome.new_device_path}.", COLOR_SUCCESS
    )
    if self.transport:
        self.iface = self.transport._iface  # refresh - watchdog reconnected the transport under us
        self._update_known_nodes()
    return

if result[0] == 'watchdog_failed':
    outcome = result[1]
    if self.power_control is None:
        # The common client case: no relay hardware configured, so the
        # watchdog can only detect a wedge, never recover it - this
        # isn't a failed recovery attempt, just an honest "you'll need
        # to reconnect it yourself" report.
        self.status_log.add_message(
            "Device appears unresponsive. Please reconnect it manually.", COLOR_WARNING
        )
    else:
        self.status_log.add_message(
            f"Automatic device recovery failed: {outcome.error}", COLOR_ERROR
        )
    return
```

---

## Critical Files

| File | Change |
|------|--------|
| `btcmesh_client_gui.py` | New watchdog state, `_start_watchdog_thread()`, `build_device_watchdog()` call in `_handle_result()`'s `transport_ready` branch, new `watchdog_attempt`/`watchdog_recovered`/`watchdog_failed` result branches, cleanup in `_disconnect_device()`/`BTCMeshApp.on_stop()` |
| `tests/test_btcmesh_client_gui.py` | Tests for the new wiring, following this file's existing lightweight pattern (`gui = MagicMock()`, call the target method unbound as `btcmesh_client_gui.BTCMeshGUI._method(gui, ...)`) rather than constructing a real `BTCMeshGUI()` |
| `project/tasks.txt` | Mark Story 28.4 done once complete |

No changes to `client/sender.py`, `core/device_watchdog.py`, or
`btcmesh_client_cli.py` (CLI is out of scope - see `project/plans/story_26_6.md`'s
original CLI-scoping reasoning, which still applies unchanged).

---

## Implementation Progress

**Done.** All items implemented and tested.

- [x] New watchdog state in `__init__`
- [x] `build_device_watchdog()` wired into `_handle_result()`'s
      `transport_ready` branch, followed by `_start_watchdog_thread()`
- [x] `_start_watchdog_thread()` - dedicated background thread, gated on
      `self._active_sender`
- [x] `watchdog_attempt`/`watchdog_recovered`/`watchdog_failed` result
      handling, including the `power_control is None` message distinction
- [x] `self.iface` refresh + `_update_known_nodes()` on `watchdog_recovered`
- [x] Cleanup in `_disconnect_device()` and `BTCMeshApp.on_stop()`
- [x] Tests: `tests/test_btcmesh_client_gui.py::TestDeviceWatchdogStory284`
      (8 tests). Full suite: 732 tests passing.

---

## Key Design Decisions

(Carried over from `project/plans/story_26_6.md`, plus one new item.)

1. **GUI only, CLI out of scope** - the CLI's one-shot lifecycle doesn't
   have an idle period for a heartbeat to run during.
2. **Dedicated background thread, not `Clock.schedule_interval`** -
   avoids freezing the GUI's main thread during a blocking `tick()` call.
3. **Heartbeat only, no `record_failure()`/`record_success()` wiring
   into the sender** - avoids a watchdog-driven reconnect racing a live
   in-progress send; keeps `client/sender.py` untouched.
4. **Watchdog callbacks route through `self.result_queue`, not directly
   to widgets** - matches the GUI's existing thread-safety pattern.
5. **`self.iface` explicitly refreshed on `on_recovered`**.
6. **New: distinguish "no relay configured" from "recovery genuinely
   failed" in the `watchdog_failed` message** - the former is the
   normal case for most client users and shouldn't read as an error.

---

## Verification

- **Unit tests** (`tests/test_btcmesh_client_gui.py`):
  - `_handle_result(('transport_ready', transport))` calls
    `build_device_watchdog()` and `_start_watchdog_thread()`.
  - `_start_watchdog_thread()`'s loop calls `watchdog.tick()` when
    `_active_sender` is `None`, and skips it when a send is active.
  - `watchdog_attempt`/`watchdog_recovered`/`watchdog_failed` results
    each produce the expected `status_log` message; `watchdog_recovered`
    refreshes `self.iface` and calls `_update_known_nodes()`;
    `watchdog_failed` distinguishes the `power_control is None` case.
  - `_disconnect_device()` clears `self.watchdog`/`self.power_control`
    and stops the thread (`self._watchdog_running` becomes `False`).
- **Regression check**: full suite still passes.
- **Manual/real hardware** (optional, matching how Story 26.5/28.3 were
  verified): run the GUI, connect to a real device, leave it idle,
  confirm the heartbeat runs without freezing the UI, then use the
  documented wedge-reproduction recipe to force a detection and confirm
  the status log reports it correctly.
