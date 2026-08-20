# Story 28.1-28.4 Implementation Plan: Reliability Hardening from Overnight Field Testing

## Context

**Why this change:**
Running the client and server GUIs unattended overnight surfaced a real,
reproduced bug (Issue 21, `project/issues.txt`): sending a transaction
the next morning hung indefinitely (no retry messages for ~5 minutes,
meaning it never even reached the already-bounded 30s ACK-wait step),
Abort had no visible effect, and the entire GUI window eventually became
completely unresponsive, requiring a force-kill. Physically unplugging
the device made no difference to the already-frozen application.

**Root cause**: `TransactionSender._send_all_chunks()` (`client/sender.py`)
calls `self.transport.send(...)` synchronously with no timeout at all -
the one call in the whole send path with no bound. The 30s ACK-wait
timeout only starts *after* `send()` returns, and the abort flag is only
checked after that wait completes. If the underlying
`MeshtasticSerialTransport.send()` → `iface.sendText(...)` call itself
never returns, nothing in the current design can interrupt it. That
unplugging the device didn't unstick the frozen application points away
from a simple OS/driver-level write() block (which physical removal
would typically eventually clear) and toward a Python-level lock held
inside the Meshtastic library itself - consistent with the *entire*
window freezing, not just the send operation.

**Why this went undetected until it caused a full freeze**: neither GUI
has any liveness check running during idle time. The client has no
`DeviceWatchdog` at all (Story 26.6 was explicitly decided against).
Checking whether the *server* needed to recover overnight turned up a
related gap: `btcmesh_server_gui.py` (what was actually run, not the
CLI) has no `DeviceWatchdog` wiring either - Story 26.5 only covered
`btcmesh_server_cli.py`, and the GUI wiring was scoped out as a
follow-up that was never implemented. The server log's overnight
silence isn't evidence nothing needed recovering - there was nothing
running that would have logged it either way.

**Four fixes, addressing this from both ends** (stop the freeze from
being possible at all, and catch a wedge before it causes one):

1. **28.1** - bound the one unbounded call, at the shared transport
   layer, so this class of freeze becomes structurally impossible
   regardless of what's causing any particular hang.
2. **28.2** - give an operator a positive "still alive" signal in the
   log, addressing the separate but related complaint that there's
   currently no way to tell the server is genuinely still running.
3. **28.3** - close the server GUI's watchdog gap (Story 26.5's
   original scoped-out follow-up), since that's what's actually run for
   real overnight operation, not the CLI.
4. **28.4** - revive Story 26.6 in a smaller, detection-only form. The
   original decision against it was reasoned around *automatic
   recovery* requiring relay hardware most client machines won't have -
   that reasoning still holds. But it under-weighted the standalone
   value of *detection alone*: `build_device_watchdog()` already
   degrades gracefully to detect-only when `power_control` is `None`,
   so a heartbeat that only ever reports "device unresponsive" (never
   attempts a power cycle) is a much smaller addition than originally
   scoped, and would have caught this exact overnight wedge - showing
   the connection as unresponsive - before the user ever tried to send
   into it.

---

## Design

### Story 28.1 - `transport/meshtastic_serial.py`

```python
class MeshtasticSerialTransport(BaseTransport):
    _WANT_ACK: bool = False
    _RECEIVE_TOPIC: str = "meshtastic.receive"
    _SEND_TIMEOUT_SECONDS: float = 10.0
    # A generous bound over sendText()'s normal near-instant completion
    # (see project/plans/story_26_2.md - raw writes return in ~0ms even
    # against a wedged device in the common case), while still far short
    # of the multi-minute hang observed in Issue 21. A class attribute
    # (matching _WANT_ACK/_RECEIVE_TOPIC's existing pattern) so tests can
    # override it per-instance without a real multi-second wait.

    def send(self, message: str, destination: str) -> None:
        if self._iface is None:
            raise TransportConnectionError("Not connected")

        outcome: dict = {}

        def _do_send():
            try:
                self._iface.sendText(
                    text=message,
                    destinationId=destination,
                    wantAck=self._WANT_ACK,
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=_do_send, daemon=True)
        worker.start()
        worker.join(timeout=self._SEND_TIMEOUT_SECONDS)

        if worker.is_alive():
            # Can't forcibly kill the underlying blocked call - it's
            # abandoned, not stopped. This still fixes the actual bug:
            # the caller (and whatever's waiting on it - a retry loop,
            # an abort flag, a GUI thread) is no longer held hostage by
            # it forever.
            raise TransportSendError(
                f"Send timed out after {self._SEND_TIMEOUT_SECONDS}s - "
                "device may be unresponsive"
            )
        if "error" in outcome:
            raise TransportSendError(
                f"Failed to send message: {outcome['error']}"
            ) from outcome["error"]
```

Deliberately *not* a `core/constants.py` entry: that module is
documented as BTCMesh protocol constants specifically, and this is a
transport-layer I/O concern (how long to wait for the underlying serial
write), not a protocol-level one - keeping `transport/` self-contained
and protocol-agnostic per this project's own layering rules.

### Story 28.2 - periodic liveness logging

Both `btcmesh_server_cli.py`'s `run_server()` loop and
`btcmesh_server_gui.py`'s `on_start_pressed()`'s `run_server()` closure
already have a `while ...: ... time.sleep(1)` loop with an existing
"every N seconds" pattern (`check_timeouts()`'s 10s cadence). Add a
second, longer-period check alongside it:

```python
LIVENESS_LOG_INTERVAL_SECONDS = 300  # 5 minutes

# in the loop, alongside the existing cleanup-cadence check:
if now - last_liveness_log >= LIVENESS_LOG_INTERVAL_SECONDS:
    active = len(receiver.get_active_sessions())
    server_logger.info(f"Server heartbeat: alive, listening. {active} active session(s).")
    last_liveness_log = now
```

(GUI version routes the same message through `self.result_queue.put(('log', ..., logging.INFO))`
instead of calling `server_logger` directly, matching how every other
GUI log line in that loop already works.)

### Story 28.3 - `btcmesh_server_gui.py`

Mirrors `btcmesh_server_cli.py`'s Story 26.5 wiring exactly, adapted to
route through `result_queue` instead of direct `server_logger` calls
(matching every other callback in this GUI's `run_server()` closure):

- After the existing `'meshtastic_connected'` push (right after
  `transport.connect()` succeeds), call `build_device_watchdog(transport, ...)`
  with callbacks that push `('log', ..., level)` results, same shape as
  `on_chunk_received`/`on_broadcast`/etc. already do.
- `TransactionReceiver(...)`'s constructor call gains
  `on_transport_error=lambda e: watchdog.record_failure()`.
- The existing `while not self._stop_event.is_set(): ... time.sleep(1)`
  loop gains `watchdog.tick(now)` alongside the existing
  `check_timeouts()` cadence check and the new Story 28.2 liveness log.

**Superseded by a fix found in review - see `project/plans/story_28_3.md`
for the full design and reasoning:** the sketch above (and the initial
implementation) wired `record_success()` into `on_chunk_received` - a
real asymmetry with `on_transport_error`, which already fires for *any*
failed reply send, not just chunk-acks. `TransactionReceiver` gains a
new `on_transport_success` callback (`server/receiver.py`), fired inside
`_send()` symmetric with `on_transport_error`, and both the CLI's
already-merged Story 26.5 wiring and this story's GUI wiring move
`record_success()` there instead of `on_chunk_received`. This keeps the
watchdog's signal purely about local transport health - never
chunk-protocol validity or remote-peer ACKs - consistently on both the
success and failure side.

### Story 28.4 - client GUI, detection-only watchdog

This is Story 26.6's already-drafted design (`project/plans/story_26_6.md`),
essentially unchanged - the dedicated background thread (not
`Clock.schedule_interval`, for the same reason documented there:
`tick()` can block, though in detect-only mode without a relay the
blocking is bounded by `check_alive()`'s own ~20s timeout, not a full
multi-minute recovery cycle), gated to skip while `self._active_sender`
is set, with results routed through `self.result_queue`. One addition:
distinguish the "no power control configured" outcome from a genuine
"tried and failed to recover" one in the message shown, since for most
client users the former will be the *normal*, expected outcome, not an
edge case:

```python
elif result[0] == 'watchdog_failed':
    outcome = result[1]
    if self.power_control is None:
        self.status_log.add_message(
            "Device appears unresponsive. Please reconnect it manually.",
            COLOR_WARNING,
        )
    else:
        self.status_log.add_message(
            f"Automatic device recovery failed: {outcome.error}", COLOR_ERROR
        )
```

---

## Critical Files

| File | Change |
|------|--------|
| `transport/meshtastic_serial.py` | Bound `send()` with a worker-thread timeout (28.1) |
| `tests/test_meshtastic_serial_transport.py` | Test for the timeout path (28.1) |
| `btcmesh_server_cli.py` | Periodic liveness log (28.2); fix `record_success()` wiring to use `on_transport_success` instead of `on_chunk_received` (28.3 review fix) |
| `btcmesh_server_gui.py` | Periodic liveness log (28.2); `build_device_watchdog()` wiring, `on_transport_error`/`on_transport_success`, `watchdog.tick()` in the loop (28.3) |
| `server/receiver.py` | Add `on_transport_success` callback, fired in `_send()` symmetric with `on_transport_error` (28.3 review fix - see `project/plans/story_28_3.md`) |
| `tests/test_btcmesh_server_cli.py` | Test for the liveness log (28.2); updated tests for the `on_transport_success` wiring (28.3 review fix) |
| `tests/test_btcmesh_server_gui.py` | Tests for the liveness log (28.2) and watchdog wiring (28.3) |
| `tests/test_server_receiver.py` | Test for `on_transport_success` (28.3 review fix) |
| `btcmesh_client_gui.py` | Detection-only watchdog thread, result handling incl. the no-power-control message distinction (28.4) |
| `tests/test_btcmesh_client_gui.py` | Tests for 28.4, reusing the plan already written in `project/plans/story_26_6.md` |
| `project/plans/story_26_6.md` | Update decision - reopened, see below |
| `project/issues.txt` | Mark Issue 21 fixed once complete |
| `project/tasks.txt` | Mark Stories 28.1-28.4 done once complete |

---

## Key Design Decisions

1. **Fix at the transport layer, not per-caller** - `client/sender.py`
   and `server/receiver.py` both call the same `transport.send()`; a
   single fix there protects both without duplicating timeout-wrapping
   logic in each caller.
2. **A worker thread + join-timeout, not a `write_timeout` on the
   underlying serial object** - `meshtastic.serial_interface.SerialInterface`
   constructs its own internal stream; there's no clean, stable way to
   reach in and set a raw pyserial `write_timeout` without depending on
   library internals that could change. A thread-based bound works
   regardless of *why* the underlying call is stuck (this project's own
   investigation only has a working theory - a Python-level lock -
   without full certainty).
3. **The stuck worker thread is abandoned, not killed** - Python can't
   forcibly terminate a thread blocked in a C-level call. This is an
   accepted, deliberate trade-off: one leaked background thread is far
   better than the whole application freezing, which is the actual bug
   being fixed.
4. **28.4 revives 26.6 rather than treating it as a new story** - the
   original decision's reasoning about relay hardware not being present
   on client machines still holds; what changed is recognizing that
   *detection alone* (already a graceful degradation `build_device_watchdog()`
   already supports) has real standalone value this incident
   demonstrated directly, independent of whether automatic recovery is
   ever possible.
5. **28.2's liveness interval (5 minutes) is a log-noise/usefulness
   trade-off, not tied to any other timing constant** - frequent enough
   to bound how long a truly-silent failure could go unnoticed, sparse
   enough not to flood the log during otherwise-quiet operation.

---

## Implementation Progress

- **Story 28.1 - Done, real-hardware verified.** `send()`'s worker-thread
  timeout wrapper is implemented and unit-tested
  (`tests/test_meshtastic_serial_transport.py::test_send_raises_timeout_error_when_sendtext_blocks`).
  Verified end-to-end against a real, genuinely unresponsive device
  (relay power-cut) via `scripts/hw_tests/send_timeout_test.py`: `send()`
  returned a `TransportSendError` after exactly the configured 10s bound
  instead of hanging. See Issue 21 in `project/issues.txt` for the full
  output and a related finding (`SerialInterface` opens its underlying
  port with `write_timeout=0`, which refines the root-cause theory -
  weakens "blocked in a raw write() syscall" in favor of "stuck holding
  a Python-level lock inside the Meshtastic library").
- **Story 28.2 - Done.** Both server entry points log
  `"Server heartbeat: alive, listening. N active session(s)."` every 5
  minutes. Unit-tested in `tests/test_btcmesh_server_cli.py::TestRunServerLivenessLog`
  and `tests/test_btcmesh_server_gui.py::TestServerLivenessLogStory282`.
- **Story 28.3 - Done, including the review fix.**
  `btcmesh_server_gui.py` builds and ticks a `DeviceWatchdog` the same
  way the CLI does - `build_device_watchdog()` called right after
  `transport.connect()` succeeds, `watchdog.tick(now)` added to the
  existing maintenance loop, all callback output routed through
  `result_queue` rather than calling `server_logger` directly.
  **Review fix applied**: the initial wiring had `record_success()` in
  `on_chunk_received` (matching the CLI's existing Story 26.5 pattern) -
  an asymmetry with `on_transport_error`, which already fires for any
  failed reply send, not just chunk-acks. Fixed via a new
  `on_transport_success` callback on `TransactionReceiver`
  (`server/receiver.py`), fired in `_send()` symmetric with
  `on_transport_error` - applied to both the GUI and the already-merged
  CLI. See `project/plans/story_28_3.md` for the full design. Unit-tested
  across `tests/test_server_receiver.py::TestTransactionReceiverTransportSuccess`,
  `tests/test_btcmesh_server_cli.py::TestBuildReceiver`, and
  `tests/test_btcmesh_server_gui.py::TestServerDeviceWatchdogStory283`.
  Full suite: 724 tests passing.
- **Story 28.4 - Done.** Detection-only `DeviceWatchdog` wired into the
  client GUI, reviving Story 26.6 in a smaller form (no relay/recovery
  hardware assumed - detection only). Dedicated background thread
  (not `Clock.schedule_interval`, which would freeze the GUI's main
  thread during a blocking `tick()` call), gated on `self._active_sender`
  so it never races an in-progress send; results routed through
  `self.result_queue`; `self.iface` explicitly refreshed on recovery.
  See `project/plans/story_28_4.md` for the full design. Unit-tested in
  `tests/test_btcmesh_client_gui.py::TestDeviceWatchdogStory284`
  (8 tests). Full suite: 732 tests passing.

**All 4 stories are implemented and unit-tested (732 tests passing).**
Only Story 28.1 (the send timeout itself - the actual freeze Issue 21
is about) has been verified against real hardware so far; Stories
28.2-28.4 still need real-hardware verification before this epic can be
considered fully done. See Issue 21 in `project/issues.txt` for the
field-incident writeup this epic responds to.

---

## Verification

- **Unit tests**:
  - `send()`: normal case unchanged (mocked `sendText` returns
    normally); a `sendText` that blocks past `_SEND_TIMEOUT_SECONDS`
    (overridden to a short value in the test) raises `TransportSendError`
    mentioning the timeout, without the test itself waiting the real
    default duration.
  - Liveness log: fires after the configured interval elapses, with the
    expected message and active-session count.
  - Server GUI watchdog wiring: mirrors the existing
    `tests/test_btcmesh_server_cli.py::TestRunServerDeviceWatchdog`
    coverage, adapted for the GUI's `result_queue` pattern.
  - Client GUI watchdog: reuses the test plan already written in
    `project/plans/story_26_6.md`'s Verification section, plus a new
    case for the `power_control is None` message wording.
- **Regression check**: full suite still passes.
- **Manual/real hardware**: reproduce the original incident's shape (a
  device that stops responding while idle) and confirm: the client GUI
  now shows a "device appears unresponsive" message during idle time
  instead of silently doing nothing; a subsequent send either works
  (device came back) or fails within seconds via the new send timeout,
  never hangs for minutes; Abort remains functional throughout.
