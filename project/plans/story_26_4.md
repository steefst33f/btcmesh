# Story 26.4 Implementation Plan: `DeviceWatchdog`

## Context

**Why this change:**
This is the core orchestration piece of EPIC 5 (Device Power-Cycle
Recovery/Watchdog, see `project/plans/story_26_1.md`), tying together the
pieces already built and hardware-verified this epic: `BasePowerControl`
(Story 26.1/26.7 - real power-cycling), `check_alive()` (Story 26.2 - a
genuine liveness signal), and `scan_meshtastic_devices_detailed()` (Story
26.3 - device path/serial_number enumeration). `DeviceWatchdog` detects a
wedged device via two complementary signals (repeated send/connect
failures, and a periodic liveness heartbeat) and drives the recovery
cycle: disconnect, power-cycle, wait for genuine re-enumeration, reconnect.

**Design constraints established by earlier stories, all directly
shaping this one:**
- `check_alive()` can block up to ~20s in the unhealthy case (Story
  26.2) - `DeviceWatchdog` must not spawn its own background thread that
  could call this concurrently with other `_iface` access; instead it's
  **caller-driven** (`tick()` called from whatever loop the server/client
  already runs, same as `TransactionReceiver.check_timeouts()`'s existing
  pattern) - this also sidesteps the thread-safety question Story 26.2
  deferred to this story entirely, since everything then runs on one
  thread.
- Path-visibility is **not** proof a device is functionally ready (Story
  26.1's finding) - the re-enumeration wait must perform a real
  `transport.connect()` attempt, not just check if a path appears in a
  scan.
- `serial_number` is **best-effort, not guaranteed-unique or even
  present** (Story 26.3's finding: chip-dependent, sometimes `None`,
  sometimes a shared factory default across multiple boards of the same
  cheap product) - not trustworthy enough to be the primary identity
  check on its own.

**Revised during implementation review - matching by `local_node_id`,
not `serial_number`/path bookkeeping:**
The original sketch (still reflected in `project/plans/story_26_1.md`'s
epic-level draft) matched candidates by `serial_number`, falling back to
"the one new path that appeared since before disconnecting." Review
caught a real bug in that fallback: it only helps when the device's path
*changes* after the power cycle - but a clean recovery is more likely to
bring the device back under the *same* path, which the "new path" check
would then fail to recognize whenever `serial_number` is `None` or
doesn't match (a real possibility per Story 26.3's chip-dependent
findings) - backwards from what a fallback should do.

The fix: the Meshtastic **node ID** (`transport.local_node_id`, e.g.
`!aee5ab3c`) is the device's own real, persistent application-layer
identity - unrelated to any USB descriptor quirk, and far more reliable
than `serial_number`. It can't be read from a bare port scan (only after
completing the connection handshake), but `_wait_for_device`'s existing
real-connect probe step already connects to each candidate anyway, so
checking `local_node_id` there is essentially free. This drops the
"before/after path" bookkeeping entirely: for each visible candidate,
connect and check `local_node_id` - a match is authoritative; a mismatch
means it's some other device, so disconnect and try the next candidate.

**Revised again - candidate enumeration moved onto `BaseTransport`, not
imported directly from `core.meshtastic_utils`:**
A second review round caught that `DeviceWatchdog` was only
*pretending* to be transport-agnostic: it accepted a generic
`BaseTransport`/`BasePowerControl`, but `_wait_for_device` directly
imported and called `scan_meshtastic_devices_detailed()` - 100%
Meshtastic-serial-specific (VID blacklists, `serial.tools.list_ports`).
Per this project's own architecture (`transport/` is meant to support
"different protocols... and connections (serial, BLE, WiFi)"), a future
BLE transport has no "path" concept at all - this would have silently
broken for anything but `MeshtasticSerialTransport`.

Fix: added `scan_for_reconnect_candidates() -> List[str]` as a new
abstract method on `BaseTransport` itself. `MeshtasticSerialTransport`
implements it by calling `scan_meshtastic_devices_detailed()`
internally; `DeviceWatchdog` now calls
`self._transport.scan_for_reconnect_candidates()` and no longer imports
`core.meshtastic_utils` at all. Device discovery becomes the concrete
transport's job (like `connect`/`local_node_id` already are), not
something the orchestration layer special-cases.

---

## Design

### `core/device_watchdog.py`

```python
from dataclasses import dataclass
from typing import Callable, Optional
import time

from transport.base import BaseTransport, TransportConnectionError
from transport.power_control import BasePowerControl, PowerControlError


@dataclass
class RecoveryOutcome:
    success: bool
    new_device_path: Optional[str] = None
    error: Optional[str] = None


class DeviceWatchdog:
    def __init__(
        self,
        transport: BaseTransport,
        power_control: Optional[BasePowerControl],
        device_node_id: Optional[str],
        max_consecutive_failures: int = 3,
        heartbeat_interval_seconds: float = 60.0,
        max_reenumerate_wait_seconds: float = 60.0,
        on_recovery_attempt: Optional[Callable[[], None]] = None,
        on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
        on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
    ):
        # device_node_id: the Meshtastic node ID (e.g. '!aee5ab3c') this
        # watchdog is guarding, captured from the transport's own
        # local_node_id while it was still working - the authoritative
        # identity check during recovery (see _try_candidate). If None,
        # any device that connects during recovery is accepted - only
        # safe when exactly one Meshtastic device is ever expected on
        # this machine (the normal single-device deployment, Story 26.7).
        self._transport = transport
        self._power_control = power_control
        self._device_node_id = device_node_id
        self._max_consecutive_failures = max_consecutive_failures
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._max_reenumerate_wait_seconds = max_reenumerate_wait_seconds
        self._on_recovery_attempt = on_recovery_attempt
        self._on_recovered = on_recovered
        self._on_recovery_failed = on_recovery_failed

        self._consecutive_failures = 0
        self._last_heartbeat_time = 0.0

    def record_success(self) -> None:
        """Call after any successful send/receive/connect - resets the
        consecutive-failure counter."""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Call after any failed send/connect. Trips recovery once
        max_consecutive_failures is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            self._recover()

    def tick(self, now: float) -> None:
        """Caller-driven heartbeat clock - call this periodically (e.g.
        once per second) from the same loop that already drives
        check_timeouts()-style polling. Only performs the (potentially
        slow) liveness check once heartbeat_interval_seconds has elapsed
        since the last one."""
        if now - self._last_heartbeat_time < self._heartbeat_interval_seconds:
            return
        self._last_heartbeat_time = now
        if not self._transport.check_alive():
            self._recover()

    def _recover(self) -> None:
        if self._on_recovery_attempt:
            self._on_recovery_attempt()

        self._transport.disconnect()

        if self._power_control is None:
            self._fail("No power control configured - cannot recover automatically")
            return

        try:
            self._power_control.power_cycle()
        except PowerControlError as e:
            self._fail(f"Power cycle failed: {e}")
            return

        matched_path = self._wait_for_device()
        if matched_path is None:
            self._fail("Device did not reappear within the wait window")
            return

        # _try_candidate() already connected as part of confirming the
        # match - nothing more to do here.
        self._consecutive_failures = 0
        outcome = RecoveryOutcome(success=True, new_device_path=matched_path)
        if self._on_recovered:
            self._on_recovered(outcome)

    def _wait_for_device(self) -> Optional[str]:
        """Poll for the device's reappearance with backoff, connecting to
        each candidate the transport reports (transport-specific - see
        BaseTransport.scan_for_reconnect_candidates()) and checking its
        real node ID via local_node_id - the only fully authoritative
        identity signal (OS-level path/serial_number are both
        unreliable)."""
        deadline = time.time() + self._max_reenumerate_wait_seconds
        delay = 2.0
        while time.time() < deadline:
            for path in self._transport.scan_for_reconnect_candidates():
                if self._try_candidate(path):
                    return path
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
        return None

    def _try_candidate(self, path: str) -> bool:
        """Connect to a candidate path and check whether it's genuinely
        our device via its real Meshtastic node ID - not just whether the
        path connects at all, since a stale path can appear in scan
        results before the device is functionally ready, and a machine
        can have more than one Meshtastic-like device connected.

        Leaves the transport connected on a match (the caller doesn't
        need to reconnect); disconnects again on a mismatch.
        """
        try:
            self._transport.connect(path)
        except TransportConnectionError:
            return False

        if (
            self._device_node_id is None
            or self._transport.local_node_id == self._device_node_id
        ):
            return True

        self._transport.disconnect()
        return False

    def _fail(self, message: str) -> None:
        if self._on_recovery_failed:
            self._on_recovery_failed(RecoveryOutcome(success=False, error=message))
```

### Explicit non-goals for this story

- Wiring this into `btcmesh_server_gui.py`/`btcmesh_server_cli.py`/client
  equivalents is Story 26.5/26.6 - this story only builds and unit-tests
  the standalone `DeviceWatchdog`, matching how 26.1/26.2/26.3/26.7 were
  each scoped independently.
- Re-registering the message handler after recovery is the *caller's*
  responsibility inside `on_recovered` (per the epic plan's existing
  design decision) - `DeviceWatchdog` never touches
  `set_message_handler`/`TransactionReceiver`/`TransactionSender`
  internals at all.

---

## Critical Files

| File | Change |
|------|--------|
| `core/device_watchdog.py` | New - `RecoveryOutcome`, `DeviceWatchdog` |
| `transport/base.py` | Add `scan_for_reconnect_candidates()` abstract method |
| `transport/meshtastic_serial.py` | Implement it via `scan_meshtastic_devices_detailed()` |
| `tests/test_device_watchdog.py` | New - full unit test coverage |
| `tests/test_transport_base.py` | `StubTransport` + ABC enforcement test |
| `tests/test_meshtastic_serial_transport.py` | New test class for the new method |
| `project/plans/story_26_1.md` | Mark Story 26.4 done once complete |

---

## Key Design Decisions

1. **Caller-driven `tick()`, no internal thread** — resolves Story 26.2's
   deferred thread-safety question by construction: `check_alive()` and
   all transport/power-control calls only ever run on whatever thread
   calls `tick()`/`record_failure()`, matching
   `TransactionReceiver.check_timeouts()`'s existing pattern exactly.
2. **Match by `local_node_id`, not `serial_number`/path bookkeeping** —
   the device's real Meshtastic identity is authoritative and free to
   check during the probe-connect step that already has to happen;
   `serial_number` is chip-dependent and sometimes absent/non-unique
   (Story 26.3), and a "new path" heuristic backwards-fails in the
   common case where the path doesn't actually change. A mismatch means
   trying the *next* candidate, not giving up - a machine can have more
   than one Meshtastic-like device connected.
3. **Real `connect()` probe, not just path visibility, before accepting
   a match** — direct response to Story 26.1's finding that a
   freshly-appeared path isn't proof the device is actually ready yet.
4. **Single recovery attempt per trip, no auto-retry loop** — mirrors the
   already-established "graceful no-op without power control configured"
   philosophy: on any failure, report `on_recovery_failed` and stop:
   hammering `power_cycle()` in a tight retry loop is worse than
   surfacing the failure once and letting the operator/caller decide.
5. **Candidate enumeration lives on `BaseTransport`, not imported
   directly** — `DeviceWatchdog` calls
   `self._transport.scan_for_reconnect_candidates()` rather than
   importing `core.meshtastic_utils` itself. Keeps the orchestration
   layer genuinely protocol-agnostic (a future BLE transport implements
   the same method its own way); device discovery is a transport concern,
   matching how `connect`/`local_node_id` already work.

---

## Verification

- **Unit tests** (mocked `BaseTransport`/`BasePowerControl` via
  `Mock(spec=...)`, matching `tests/test_server_receiver.py`'s existing
  convention; `transport.scan_for_reconnect_candidates` configured
  directly on the mock - `DeviceWatchdog` itself never touches
  `core.meshtastic_utils`):
  - `record_failure()` trips recovery exactly at `max_consecutive_failures`,
    not before; `record_success()` resets the counter.
  - `tick()` only calls `check_alive()` once `heartbeat_interval_seconds`
    has elapsed; a `False` result trips recovery.
  - Full recovery success path: disconnect → power_cycle → candidate
    connects → `local_node_id` matches → `on_recovered` fires with the
    right `RecoveryOutcome` (device already connected, no second connect
    call needed).
  - `device_node_id=None` fallback: accepts whatever candidate connects
    (documented as only safe for the single-device deployment).
  - Node-ID mismatch: a candidate connects but isn't our device (wrong
    `local_node_id`) → disconnected again, next candidate tried instead.
  - No `power_control` configured → immediate `on_recovery_failed`,
    `power_cycle()`/scanning never attempted.
  - `PowerControlError` during `power_cycle()` → `on_recovery_failed`
    with that error message.
  - Re-enumeration timeout (`_wait_for_device` exhausts
    `max_reenumerate_wait_seconds`) → `on_recovery_failed`.
  - Stale-path rejection: a candidate's `connect()` fails once before
    succeeding → keeps polling rather than treating it as a final
    failure (regression test for Story 26.1's specific finding).
- **Regression check**: full suite still passes.
- **Real hardware** (recommended once built, using the wedge-reproduction
  recipe already documented in `project/plans/story_26_2.md`, and the
  relay wired for Story 26.7): construct a real `DeviceWatchdog` around
  the actual relay-equipped device, wedge it, call `tick()`/
  `record_failure()` and confirm it genuinely recovers end-to-end.

---

## Implementation Completion

**Status:** Done. `core/device_watchdog.py` implemented exactly as
designed above, including both mid-review redesigns: `serial_number`/path
matching → `local_node_id` matching, and direct `core.meshtastic_utils`
import → `BaseTransport.scan_for_reconnect_candidates()`.
`tests/test_device_watchdog.py` (15 tests), `tests/test_transport_base.py`,
and `tests/test_meshtastic_serial_transport.py` all updated/extended
accordingly, all passing.

**Not yet done**: the real-hardware end-to-end test listed above (wedge
a relay-equipped device, run a real `DeviceWatchdog` against it) - left
for whenever hardware time is available, since this story's unit test
coverage already exercises every branch with mocks. Also not done (by
design, out of scope for this story): wiring into `btcmesh_server_gui.py`/
`btcmesh_server_cli.py`/client equivalents - that's Story 26.5/26.6.
