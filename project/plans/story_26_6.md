# Story 26.6 Implementation Plan: Wire DeviceWatchdog into the client (GUI)

## Decision: Not Implemented

After drafting the design below and getting the CLI-vs-GUI scope
question resolved (GUI only), a step back at the resulting design raised
a more fundamental question: does client-side automatic recovery
actually make sense at all? Concluded **no**, for reasons distinct from
(and stronger than) the CLI-scoping issue that had already narrowed the
story:

- **The server's whole premise is unattended operation** - EPIC 5 exists
  so a relay server can recover without a human physically
  unplugging/replugging it (see `project/plans/story_26_1.md`). The
  client GUI is used in short, attended sessions - if the device wedges,
  the user is already sitting right there and can just click "Scan" or
  physically touch the device themselves. The value of *automatic,
  unattended* recovery is much weaker when a human is already present.
- **The relay hardware this depends on almost certainly isn't present on
  a client machine.** `DeviceWatchdog` can only actually recover a
  device if `RELAY_SERIAL_PORT` is configured - a relay board spliced
  into that specific device's own VBUS wire (Story 26.7). That's
  operator infrastructure for an always-on relay node, not something a
  regular person sending a transaction from their laptop would have
  wired up. Without it, `build_device_watchdog()` returns
  `power_control=None`, and the watchdog can only detect and log
  ("device appears wedged") - it can never actually power-cycle
  anything.
- Combined, for the overwhelmingly common client deployment (no relay),
  this story would have bought a nicer "device appears unresponsive" log
  message during idle time - not actual automatic recovery - for the
  cost of a new background thread, race-gating against active sends,
  `result_queue` plumbing, and the `self.iface` refresh fix documented
  below. Too thin a payoff to justify the added complexity in an
  interactive application.

The design below is kept as a record of the analysis (including a real,
non-obvious constraint found along the way - see "Dedicated background
thread, not `Clock.schedule_interval`" - in case client-side recovery is
revisited later, e.g. if a use case emerges where relay hardware genuinely
is present on a client machine). **EPIC 5 is considered complete at the
server (Stories 26.1-26.5, 26.7); Story 26.6 is intentionally not
implemented.**

---

## Context (original, pre-decision)

**Why this change:**
Story 26.5 wired `DeviceWatchdog` into the server (`btcmesh_server_cli.py`)
and verified real automatic recovery on real hardware (see Issue 20's
resolution). This story brings the same automatic recovery to the client
GUI (`btcmesh_client_gui.py`), so a wedged Meshtastic device doesn't force
the user to close and reopen the app.

**Scope decision - GUI only, not the CLI**: `btcmesh_client_cli.py` is a
one-shot process (parse args → connect → send one transaction → exit).
Unlike the server or the GUI, it has no persistent idle period for a
heartbeat to run during - the whole premise of `DeviceWatchdog.tick()`
("call periodically, e.g. once per second, between other work") doesn't
map onto a process that runs for the duration of one send and then exits.
Both of this story's own scenarios ("idle connection" and "active send")
are naturally shaped around a long-lived process, which today only the
GUI is. CLI wiring (e.g., attempting one recovery pass after a failed
send, before exiting) is a real but *different-shaped* piece of work,
scoped out as a possible follow-up rather than folded in here - mirroring
how Story 26.5 scoped the server GUI (`btcmesh_server_gui.py`) out as a
follow-up rather than blocking on it.

**A real constraint found while designing this, not obvious from the
epic's original sketch**: the epic's rough sketch guessed a lightweight
`Clock.schedule_interval` would be enough to drive `tick()` on the GUI
side. That's not safe as-is: `DeviceWatchdog.tick()` can block for up to
~2 minutes during a real recovery cycle (power-cycle wait + reconnect
polling with backoff), and `Clock.schedule_interval` callbacks run on
Kivy's main/UI thread - calling `tick()` directly from one would freeze
the entire application window (unresponsive, looks hung) for as long as
a recovery attempt takes. This needs to run on a dedicated background
thread instead, exactly like the app's existing `init_thread`/
`send_thread` pattern, with results routed back through the existing
`self.result_queue` + `_check_results()` polling mechanism (the same
thread-safety pattern the GUI already uses for every other background
operation) rather than touching widgets directly from that thread.

**Failure-detection design**: only the idle heartbeat (`tick()`) is
wired up - `record_failure()`/`record_success()` are *not* hooked into
`TransactionSender`'s per-chunk send/ACK cycle. Hooking them in would
risk `record_failure()` crossing its trip threshold *while a send is
still in its own retry loop*, racing a live in-progress send with a
watchdog-driven disconnect/reconnect - exactly what this story's own
"Recovery during an active send" scenario says should *not* happen
("the in-flight send fails cleanly via its existing retry/timeout
handling, and the watchdog's next tick recovers the device for the next
attempt, rather than the recovery racing the send"). The heartbeat
thread is gated to skip entirely while a send is active (checked via the
GUI's own existing `self._active_sender` tracking), so recovery only
ever runs when nothing else is using the transport. This also means
`client/sender.py` needs no changes at all for this story.

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
handling (`self.transport = result[1]`):

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

(Callbacks push to `result_queue` rather than touching `status_log`
directly, since `DeviceWatchdog` will invoke them from the background
watchdog thread, not the main thread - see below.)

### The watchdog thread itself

```python
def _start_watchdog_thread(self):
    self._watchdog_running = True

    def watchdog_loop():
        while self._watchdog_running:
            if self._active_sender is None:  # don't race an active send
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

(The thread's own `while self._watchdog_running` loop notices within at
most ~1s and exits on its own; no join needed since it's a daemon thread
doing nothing unsafe if it observes stale state for one more iteration -
its next `tick()` call, if any, will just see the swapped-out transport
via closure over `self`, and `self.watchdog` will already be `None` so
it exits before calling anything on the old watchdog... actually since
`watchdog_loop` captured `self.watchdog` is read fresh each iteration via
`self.watchdog.tick(...)`, guard by checking `self.watchdog is not None`
too, to avoid a race calling `.tick()` on `None` right as it's cleared.)

Updated loop body: `if self.watchdog is not None and self._active_sender is None:`.

### Handling watchdog results in `_handle_result()`

```python
elif result[0] == 'watchdog_attempt':
    self.status_log.add_message("Device appears wedged - attempting automatic recovery...", COLOR_WARNING)
elif result[0] == 'watchdog_recovered':
    outcome = result[1]
    self.status_log.add_message(f"Device recovered. Reconnected at {outcome.new_device_path}.", COLOR_SUCCESS)
    if self.transport:
        self.iface = self.transport._iface  # refresh - watchdog reconnected the transport under us
        self._update_known_nodes()
elif result[0] == 'watchdog_failed':
    outcome = result[1]
    self.status_log.add_message(f"Automatic device recovery failed: {outcome.error}", COLOR_ERROR)
```

The `self.iface` refresh on recovery matters: `DeviceWatchdog` reconnects
the *same* `MeshtasticSerialTransport` object (it never constructs a new
transport), but `self.iface` is a separate raw-interface reference the
GUI captured for node listing (Stories 11.2/11.3) - it goes stale across
a disconnect/reconnect unless explicitly refreshed, since the watchdog
has no knowledge of that GUI-only field.

### `on_stop()`

Gains `self._watchdog_running = False` alongside the existing transport
disconnect, so the daemon thread doesn't keep ticking after app close
(harmless either way since it's a daemon thread, but tidy).

---

## Critical Files

| File | Change |
|------|--------|
| `btcmesh_client_gui.py` | New watchdog state, `_start_watchdog_thread()`, `build_device_watchdog()` call in `_handle_result()`'s `transport_ready` branch, new `watchdog_attempt`/`watchdog_recovered`/`watchdog_failed` result branches, cleanup in `_disconnect_device()`/`on_stop()` |
| `tests/test_btcmesh_client_gui.py` | Tests for the new wiring (watchdog construction, thread gating on `_active_sender`, result-handling branches, `iface` refresh on recovery) |
| `project/plans/story_26_1.md` | Mark Story 26.6 done once complete |
| `project/tasks.txt` | Mark Story 26.6 done once complete |

No changes to `client/sender.py`, `core/device_watchdog.py`, or
`btcmesh_client_cli.py` (out of scope this story, see above).

---

## Key Design Decisions

1. **GUI only, CLI out of scope** - the CLI's one-shot lifecycle doesn't
   have an idle period for a heartbeat to run during; see Context.
2. **Dedicated background thread, not `Clock.schedule_interval`** -
   `tick()` can block for up to ~2 minutes during a real recovery cycle;
   running it on Kivy's main thread would freeze the whole window. This
   is a correction to the epic's original rough sketch, found while
   actually designing this story (matching this project's precedent of
   revising early sketches once real analysis is done - see Story
   26.4's two documented redesigns).
3. **Heartbeat only, no `record_failure()`/`record_success()` wiring
   into the sender** - avoids a watchdog-driven reconnect racing a live
   in-progress send; matches the story's own explicit scenario wording.
   Keeps `client/sender.py` untouched.
4. **Watchdog callbacks route through `self.result_queue`, not directly
   to widgets** - `DeviceWatchdog` invokes them from the background
   watchdog thread, and Kivy widgets must only be touched from the main
   thread; this reuses the exact pattern the GUI already uses for every
   other background operation (connect, send, disconnect).
5. **`self.iface` explicitly refreshed on `on_recovered`** - a real gap
   that would otherwise silently break node listing after a recovery,
   found by tracing what state the GUI keeps beyond `self.transport`.

---

## Verification

- **Unit tests** (`tests/test_btcmesh_client_gui.py`, following this
  file's existing pattern of mocking Kivy modules):
  - `build_device_watchdog()` is called once a `transport_ready` result
    is processed, with `self.watchdog`/`self.power_control` set.
  - The watchdog thread's loop skips calling `tick()` while
    `self._active_sender` is set (simulate an active send, assert
    `watchdog.tick` not called; clear it, assert it is called).
  - `watchdog_attempt`/`watchdog_recovered`/`watchdog_failed` results
    each produce the expected `status_log` message.
  - `watchdog_recovered` refreshes `self.iface` from
    `self.transport._iface` and triggers `_update_known_nodes()`.
  - `_disconnect_device()` clears `self.watchdog`/`self.power_control`
    and stops the thread (`self._watchdog_running` becomes `False`).
- **Regression check**: full suite still passes.
- **Manual/real hardware** (recommended, following the same approach
  that verified Story 26.5 on real hardware): run the GUI, connect to a
  real relay-equipped device, leave it idle for a while to confirm the
  heartbeat runs without freezing the UI, then use the same manual
  `power_cycle()` trigger technique used for Issue 20 to force a
  reconnect and confirm the GUI logs the recovery and its node list
  keeps working afterward.
