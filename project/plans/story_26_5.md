# Story 26.5 Implementation Plan: Wire DeviceWatchdog into the server (CLI)

## Context

**Why this change:**
`DeviceWatchdog` (Story 26.4), `BasePowerControl` (26.1/26.7), and
`check_alive()` (26.2) are all built and unit-tested but not yet used by
anything real. This story wires them into `btcmesh_server_cli.py` - the
"first real integration point" per the epic's implementation order - so
the relay server actually recovers automatically from a wedged device
instead of just being *capable* of it in isolation.

**A real gap found while tracing the wiring, needed to fix first:**
`TransactionReceiver._send()` (`server/receiver.py`) calls
`self.transport.send(...)` with no error handling. Two different callers
hit this differently:
- Via the transport's pubsub message-dispatch (`_on_message`, triggered
  on a background thread), any exception it raises is **silently
  swallowed** by `MeshtasticSerialTransport._on_meshtastic_receive`'s own
  blanket `except Exception: logger.exception(...)` - confirmed by
  reading that code. A send failure here currently never reaches
  anything that could call `watchdog.record_failure()`.
- Via `check_timeouts()` (called directly from the CLI's own loop, not
  through pubsub), an unhandled exception would propagate all the way up
  and **crash the whole server loop** - a latent pre-existing bug,
  independent of this story, that this wiring would otherwise trip over.

**Fix**: give `TransactionReceiver` a new `on_transport_error` callback,
fired from inside `_send()` right before re-raising (so all existing
control flow/behavior is unchanged - callers like `on_chunk_received`
still correctly don't fire after a failed send, exactly as today) - and
wrap `check_timeouts()`'s per-session NACK send in the same
catch-and-continue style already used elsewhere in that file (e.g. the
`ReassemblyError` branch), so one wedged-device failure during cleanup
doesn't crash the loop or block cleaning up other sessions.

**A simplification found while re-reading the transport layer:**
The epic's original sketch assumed recovery needs "re-attach
`TransactionReceiver` to the new transport instance." That's not
actually necessary: `DeviceWatchdog` reuses the *same* `BaseTransport`
object throughout recovery (it calls `.connect()` again on it, never
constructs a new transport), and `MeshtasticSerialTransport.disconnect()`
deliberately preserves the previously-registered message handler
("Does NOT clear the message handler (preserved for reconnect)"), with
`connect()` automatically re-subscribing it if one was set. So the
*existing* `TransactionReceiver` instance keeps working unchanged across
a recovery cycle - no reconstruction needed at all.

**Scope note**: this story wires the CLI (`btcmesh_server_cli.py`) only;
`btcmesh_server_gui.py` wiring is a natural, similarly-scoped follow-up.

**Shared setup, not duplicated like `TransactionReceiver`'s wiring is**:
`btcmesh_server_gui.py` already wires its own `TransactionReceiver`
independently of the CLI's `build_receiver()` (Stories 23.2/23.3) - but
that duplication exists because the GUI's *actual reporting* genuinely
differs (thread-safe `result_queue` updates for Kivy widgets vs. direct
`server_logger` calls). `DeviceWatchdog`'s setup is different: reading
`RELAY_SERIAL_PORT`/baud/channel from config and constructing
`SerialRelayPowerControl` (or `None`), then constructing the
`DeviceWatchdog` itself, has **zero UI-specific variation** - only the
callback *bodies* passed in differ per UI. Following this project's
no-duplicated-logic principle for shared UI-facing code, this part is
extracted into a shared factory, `build_device_watchdog()` in
`core/device_watchdog.py`, so the CLI (and later the GUI) only supply
their own callback functions.

---

## Design

### `server/receiver.py`

```python
def __init__(
    self,
    ...,
    on_transport_error: Optional[Callable[[Exception], None]] = None,
    # on_transport_error(exc) - fires whenever a reply send actually fails
    # at the transport layer (device wedged/disconnected), right before
    # the exception propagates exactly as it does today. Intended for a
    # caller to hook into DeviceWatchdog.record_failure() (Story 26.5) -
    # this class has no knowledge of DeviceWatchdog itself.
):
    ...
    self._on_transport_error = on_transport_error

def _send(self, message: str, sender_id: str) -> None:
    try:
        self.transport.send(message, sender_id)
    except Exception as e:
        if self._on_transport_error:
            self._on_transport_error(e)
        raise
    if self._on_wire_sent:
        self._on_wire_sent(message)
```

`check_timeouts()`'s cleanup loop wraps `_send_nack(...)` per-session:

```python
for session_info in self.reassembler.cleanup_stale_sessions():
    try:
        self._send_nack(
            session_info["tx_session_id"],
            session_info["sender_id_str"],
            session_info["error_message"],
        )
    except Exception:
        pass  # on_transport_error already fired inside _send(); don't
              # crash the loop or block cleaning up other sessions
    if self._on_error:
        self._on_error(...)
```

### `core/config_loader.py`

Add `get_relay_channel() -> int` (default `1`, matching Story 26.7's
"single channel is the normal case"), mirroring the existing
`get_relay_serial_port()`/`load_relay_serial_baud()` getters.

### `core/device_watchdog.py` — new `build_device_watchdog()` factory

```python
def build_device_watchdog(
    transport: BaseTransport,
    on_recovery_attempt: Optional[Callable[[], None]] = None,
    on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
    on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
) -> Tuple[DeviceWatchdog, Optional[BasePowerControl]]:
    """Build a DeviceWatchdog for the given (already-connected) transport,
    reading power-control config from .env - shared by any UI layer
    (CLI/GUI) so the config-parsing + construction logic isn't duplicated;
    only the callback bodies (how to report progress) are UI-specific.

    Returns (watchdog, power_control) - power_control is also returned
    (rather than only living inside the watchdog) so the caller can log
    /display whether automatic recovery is actually enabled without
    reaching into the watchdog's internals.
    """
    from core.config_loader import (
        get_relay_channel,
        get_relay_serial_port,
        load_relay_serial_baud,
    )
    from transport.power_control import SerialRelayPowerControl

    power_control = None
    relay_port = get_relay_serial_port()
    if relay_port:
        relay_baud, _ = load_relay_serial_baud()
        power_control = SerialRelayPowerControl(
            relay_port, get_relay_channel(), relay_baud
        )

    watchdog = DeviceWatchdog(
        transport,
        power_control,
        device_node_id=transport.local_node_id,
        on_recovery_attempt=on_recovery_attempt,
        on_recovered=on_recovered,
        on_recovery_failed=on_recovery_failed,
    )
    return watchdog, power_control
```

(Imports are inside the function to avoid `core/device_watchdog.py`
importing `transport/power_control.py` at module level for a dependency
only needed when this factory is actually called - matching the lazy-import
style already used elsewhere in this codebase, e.g.
`MeshtasticSerialTransport.connect()`.)

### `btcmesh_server_cli.py`

After a successful `transport.connect()`:

```python
watchdog, power_control = build_device_watchdog(
    transport,
    on_recovery_attempt=lambda: server_logger.warning(
        "Device appears wedged - attempting automatic recovery..."
    ),
    on_recovered=lambda outcome: server_logger.info(
        f"Device recovered. Reconnected at {outcome.new_device_path}."
    ),
    on_recovery_failed=lambda outcome: server_logger.error(
        f"Automatic device recovery failed: {outcome.error}"
    ),
)
if power_control:
    server_logger.info("Automatic device-recovery enabled via relay.")
else:
    server_logger.info(
        "RELAY_SERIAL_PORT not configured - automatic device-wedge "
        "recovery is disabled (wedge detection still logs, but won't "
        "recover on its own)."
    )
```

`build_receiver()` gains a `watchdog` parameter: passes
`on_transport_error=lambda e: watchdog.record_failure()` into
`TransactionReceiver`, and the existing `on_chunk_received` closure gets
one added line, `watchdog.record_success()` - it only fires after
`_on_message()`'s ack-send has already succeeded, so it's a correct
"this send definitely worked" signal.

Main loop gains `watchdog.tick(now)` alongside the existing
`check_timeouts()` cadence check - no extra try/except needed around
`check_timeouts()` itself, since it's now internally exception-safe.

---

## Critical Files

| File | Change |
|------|--------|
| `server/receiver.py` | Add `on_transport_error` callback; make `check_timeouts()` exception-safe |
| `core/config_loader.py` | Add `get_relay_channel()` |
| `core/device_watchdog.py` | Add `build_device_watchdog()` factory (shared CLI/GUI setup) |
| `btcmesh_server_cli.py` | Call `build_device_watchdog()`, wire callbacks, `tick()` in the loop |
| `tests/test_server_receiver.py` | Tests for `on_transport_error` + `check_timeouts()` exception-safety |
| `tests/test_config_loader.py` | Test for `get_relay_channel()` |
| `tests/test_device_watchdog.py` | Tests for `build_device_watchdog()` |
| `tests/test_btcmesh_server_cli.py` | Tests for the new wiring |
| `project/plans/story_26_1.md` | Mark Story 26.5 done once complete |

---

## Key Design Decisions

1. **`on_transport_error` fires then re-raises, doesn't swallow** — keeps
   100% of `TransactionReceiver`'s existing control flow/behavior
   unchanged (e.g. `on_chunk_received` still correctly never fires after
   a failed ack send); it's purely an additive hook.
2. **No `TransactionReceiver` reconstruction on recovery** — confirmed
   unnecessary by re-reading the transport layer (see Context) - a
   genuine simplification over the epic's original sketch.
3. **`record_success()` hooked to `on_chunk_received`, not `tick()`/a
   timer** — the most immediate, correct "this device is genuinely
   working" signal available, firing only once a send has actually
   succeeded.
4. **`build_device_watchdog()` factory shared between CLI and GUI, unlike
   `TransactionReceiver`'s wiring** — the config-parsing +
   `DeviceWatchdog` construction has zero UI-specific variation (unlike
   `TransactionReceiver`'s callbacks, which genuinely need different
   reporting mechanisms per UI); extracting it avoids duplicating logic
   that has no reason to differ between UI layers. This story only
   calls it from the CLI; GUI wiring is a natural follow-up that reuses
   the same factory rather than duplicating its logic.
5. **No new watchdog-tuning env vars this story** — `DeviceWatchdog`'s
   own constructor defaults (60s heartbeat, 3 failures,
   60s reenumerate wait) are used as-is; only the relay's
   port/baud/channel are made configurable, matching this story's actual
   need. Avoids speculative config surface (YAGNI).

---

## Verification

- **Unit tests**:
  - `server/receiver.py`: `on_transport_error` fires (and the exception
    still propagates) when `transport.send()` raises during a normal
    ack-send; `on_chunk_received` does NOT fire in that case (regression
    guard); `check_timeouts()` no longer raises when `_send_nack()` fails
    during cleanup, but still fires `on_transport_error` and continues
    cleaning up remaining stale sessions.
  - `core/config_loader.py`: `get_relay_channel()` default and env
    override.
  - `build_device_watchdog()`: returns `(watchdog, None)` when
    `RELAY_SERIAL_PORT` unset; returns a real `SerialRelayPowerControl`
    (with the configured port/baud/channel) when set; callback params
    pass straight through to the constructed `DeviceWatchdog`.
  - `btcmesh_server_cli.py`: calls `build_device_watchdog()`;
    `record_failure()`/`record_success()` wired correctly via
    `build_receiver()`; `tick()` called each loop iteration.
- **Regression check**: full suite still passes.
- **Real hardware** (recommended - also closes Story 26.4's still-open
  real-hardware verification gap): run `btcmesh_server_cli.py` for real
  against the Story 26.7 relay-equipped device, reproduce a wedge (the
  recipe documented in `project/plans/story_26_2.md`), and confirm the
  server logs the recovery attempt, actually recovers, and resumes
  receiving chunks afterward without a restart.
