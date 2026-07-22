# EPIC 5 Implementation Plan: Device Power-Cycle Recovery (Watchdog)

Covers Stories 26.1-26.7. Filed under `story_26_1.md` per the plan-file naming
convention, but this document plans the whole epic since the stories are
architecturally interdependent (power control, liveness check, and watchdog
orchestration only make sense together) — implementation still proceeds
story-by-story with a review checkpoint after each, per the usual workflow.

## Context

**Why this change:**
`project/issues.txt` documents real, observed cases (Issue 12, Issue 16) of a
Meshtastic USB device becoming unresponsive — "wedged mid-boot from rapid
repeated connect/disconnect cycles," or generally "locked in" after extended
runtime — where the only fix found so far is a manual, physical power cycle:
unplug, wait 10-15s, replug. For an unattended relay server this is a hard
operational failure mode: someone has to be physically present to fix it.

**Goal:**
Detect this lockup automatically and recover by power-cycling the device's
USB port under software control — no human required.

**Outcome:**
A shared `DeviceWatchdog` used by both the server and client that:
- Notices a wedged device via two complementary signals (repeated send/connect
  failures, and a periodic liveness heartbeat)
- Power-cycles the device via a pluggable backend (uhubctl-compatible hub, or
  a DIY relay board as fallback)
- Waits for the device to re-enumerate and reconnects automatically, matching
  it by stable identity rather than assuming its OS device path is unchanged

---

## Architecture Overview

Two new pieces slot into the existing layered architecture, plus small
extensions to two existing modules:

```
transport/
├── base.py                 (existing — add check_alive() to BaseTransport)
├── meshtastic_serial.py    (existing — implement check_alive())
└── power_control.py        (NEW — abstract power-cycling interface)

core/
├── meshtastic_utils.py     (existing — scan_meshtastic_devices() gains
│                             stable serial_number alongside path)
└── device_watchdog.py      (NEW — DeviceWatchdog orchestration, shared by
                              client and server)

hardware/                   (NEW, non-Python — only if Story 26.7 is needed)
└── power_relay_firmware/
    └── power_relay.ino
```

`DeviceWatchdog` sits at the same orchestration altitude as
`client/sender.py` and `server/receiver.py`: it depends on `BaseTransport`
and the new `BasePowerControl`, has no direct hardware/library imports, and
exposes callbacks for the GUI/CLI layers to display progress — consistent
with the project's "no I/O in core/orchestration, callbacks for UI" pattern.

### Why not fold this into transport/ instead of a new core/ module?

`transport/` is deliberately protocol-agnostic communication (send/receive
bytes). Power-cycling is a different concern — it's *infrastructure around*
a transport, not communication itself — so it gets its own peer module next
to `client/`/`server/`, following the same "orchestration combines two lower
layers" pattern those already use (they combine core logic + transport;
`DeviceWatchdog` combines transport + power control).

---

## Implementation Steps

### Story 26.1 — `transport/power_control.py`

```python
class PowerControlError(Exception): ...

class BasePowerControl(ABC):
    @abstractmethod
    def power_cycle(self, off_seconds: float = 15.0) -> None:
        """Cut and restore power to the configured target.
        Raises PowerControlError on failure."""

class UhubctlPowerControl(BasePowerControl):
    def __init__(self, location: str, port: int):
        self._location = location
        self._port = port

    def power_cycle(self, off_seconds: float = 15.0) -> None:
        result = subprocess.run(
            ["uhubctl", "-l", self._location, "-p", str(self._port),
             "-a", "cycle", "-d", str(off_seconds)],
            capture_output=True, text=True, timeout=off_seconds + 10,
        )
        if result.returncode != 0:
            raise PowerControlError(result.stderr or "uhubctl failed")
```

Single subprocess call — `uhubctl -a cycle -d <seconds>` already does
off→wait→on internally, so no manual `time.sleep()` is needed here.

### Story 26.2 — `check_alive()` on `BaseTransport`

Add to `transport/base.py`:

```python
@abstractmethod
def check_alive(self) -> bool:
    """Best-effort liveness check. Returns False (never raises) if not
    connected or the device doesn't respond within a short timeout."""
    ...
```

`MeshtasticSerialTransport` implementation (best current guess, **flagged as
needing real-hardware verification** — see Open Questions):

```python
def check_alive(self) -> bool:
    if self._iface is None:
        return False
    try:
        return self._iface.getMyNodeInfo() is not None
    except Exception:
        return False
```

This is a local call against the already-open interface object — it doesn't
transmit over LoRa, so it's cheap and doesn't touch the RF duty cycle. The
open question is whether it actually raises/hangs when the *serial link
itself* is wedged, versus just returning cached in-memory data regardless of
whether the device is responsive.

### Story 26.3 — stable device identity in `scan_meshtastic_devices()`

Currently returns `List[str]` of paths. Change to also carry each port's
`serial_number` (from `serial.tools.list_ports.comports()`, already the
enumeration method after the Issue 9 fix) — either as a parallel dict or by
introducing a small `DeviceInfo` dataclass (`path`, `serial_number`,
`description`). Existing callers that only want paths get a thin
`[d.path for d in devices]` at the call site; check `btcmesh_client_gui.py`'s
usage before deciding between changing the return type outright vs. adding a
new `scan_meshtastic_devices_detailed()` alongside the existing function, to
avoid an unreviewed ripple through both GUIs mid-epic.

### Story 26.4 — `core/device_watchdog.py`

```python
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
        device_serial_number: Optional[str],
        max_consecutive_failures: int = 3,
        heartbeat_interval_seconds: float = 60.0,
        max_reenumerate_wait_seconds: float = 60.0,
        on_recovery_attempt: Optional[Callable[[], None]] = None,
        on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
        on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
    ): ...

    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...   # trips recovery at threshold
    def tick(self, now: float) -> None:      # caller-driven heartbeat clock
        ...                                   # calls check_alive() on schedule,
                                               # trips recovery on False
```

Recovery cycle (`_recover()`, private):
1. `transport.disconnect()`
2. If no `power_control` configured: report failure via `on_recovery_failed`
   and stop (graceful no-op, per Story 26.5's degrade-gracefully scenario)
3. `power_control.power_cycle()` — propagate `PowerControlError` into
   `on_recovery_failed`
4. Poll `scan_meshtastic_devices()` with backoff (e.g. 2s, 4s, 8s, ... capped)
   up to `max_reenumerate_wait_seconds`, looking for `device_serial_number`
5. On match: `transport.connect(matched_path)`, re-`set_message_handler()`
   with the handler the caller originally registered (watchdog must be
   constructed with a reference to it, or the caller re-registers in the
   `on_recovered` callback — simpler, avoids the watchdog needing to know
   about message routing at all)
6. Report `on_recovered`/`on_recovery_failed` with a `RecoveryOutcome`

Design choice: re-registering the message handler is the *caller's*
responsibility inside `on_recovered`, not the watchdog's — keeps
`DeviceWatchdog` from needing to know anything about `TransactionReceiver`/
`TransactionSender` internals, matching the existing callback-based
decoupling used throughout this codebase.

### Story 26.5 / 26.6 — wiring into server/client

Server: extend the existing loop at
[btcmesh_server_gui.py:856-862](../../btcmesh_server_gui.py#L856-L862) —
add `watchdog.tick(time.time())` alongside the existing `check_timeouts()`
cadence check, and route `record_failure()`/`record_success()` calls from
wherever `TransactionReceiver`'s transport-level exceptions currently
surface. On `on_recovered`, re-attach `TransactionReceiver` to the new
transport instance (construct a fresh `TransactionReceiver` with the same
callbacks — it re-registers its own handler in `__init__`).

Client: same pattern, but the client doesn't have a standing background loop
when idle — needs a lightweight `Clock.schedule_interval` (GUI) or a small
poll loop (CLI) purely to drive `watchdog.tick()` even between sends.

### Story 26.7 — DIY relay fallback (build only if uhubctl fails on real hardware)

`SerialRelayPowerControl` opens a *second* serial connection (to the
companion microcontroller, not the Meshtastic device) and speaks a minimal
line protocol:

```
→ CYCLE 1 15\n      (channel 1, off for 15s)
← OK\n              (or ERR <reason>\n)
```

Matching Arduino sketch (`hardware/power_relay_firmware/power_relay.ino`)
reads lines from `Serial`, parses `CYCLE <channel> <seconds>`, drives the
corresponding relay/MOSFET GPIO pin low then high after the delay, writes
back `OK`. Wiring: relay/MOSFET spliced into the LoRa device's USB extension
cable's VBUS wire only (D+/D- untouched), driven by the Arduino's GPIO.

---

## Critical Files

| File | Change |
|------|--------|
| `transport/power_control.py` | New — `BasePowerControl`, `UhubctlPowerControl`, `PowerControlError` |
| `transport/base.py` | Add `check_alive()` abstract method |
| `transport/meshtastic_serial.py` | Implement `check_alive()` |
| `core/meshtastic_utils.py` | `scan_meshtastic_devices()` gains stable serial number |
| `core/device_watchdog.py` | New — `DeviceWatchdog`, `RecoveryOutcome` |
| `btcmesh_server_gui.py` | Wire watchdog into existing background loop |
| `btcmesh_client_gui.py` | Wire watchdog into a new idle-tick loop |
| `hardware/power_relay_firmware/power_relay.ino` | New — only if Story 26.7 needed |
| `.env.example` | New config keys: power-control backend selection + target |

---

## Key Design Decisions

1. **Watchdog doesn't own message-handler re-registration** — caller's
   responsibility in `on_recovered`, keeping `DeviceWatchdog` decoupled from
   `TransactionReceiver`/`TransactionSender` (see Story 26.4).

2. **Match by stable serial number, not device path** — USB re-enumeration
   after a power cycle can assign a new `/dev/cu.usbserial-*` path on macOS;
   path-based matching would silently reconnect to the wrong port if a second
   device is present, or fail to reconnect at all.

3. **Graceful no-op without power control configured** — a user who hasn't
   set up hardware yet still benefits from lockup *detection* and logging,
   just not automatic recovery. Avoids forcing hardware setup as a
   prerequisite for the rest of this epic.

4. **`uhubctl` before DIY hardware** — Story 26.7 (relay + firmware) is
   explicitly last and conditional: only build it once `uhubctl -l` is
   confirmed incompatible with the actual hub in use.

---

## Open Questions Requiring Real-Hardware Verification

These can't be resolved from the repo alone and should be tested against
real devices before finalizing 26.2 and 26.7:

1. **Does `iface.getMyNodeInfo()` (or an equivalent local call) actually fail
   against a genuinely wedged device**, or does it return cached in-memory
   data regardless of whether the serial link is responsive? If the latter,
   a different liveness signal is needed (e.g. checking the reader thread's
   last-activity timestamp, or a lower-level serial port health check).
2. **Is the operator's USB hub `uhubctl`-compatible at all?** Run
   `uhubctl -l` against the actual hardware before committing to Story 26.1
   as the primary path.
3. **How long does re-enumeration actually take** on the target OS/hub after
   a power cycle, to calibrate `max_reenumerate_wait_seconds` sensibly.

---

## Verification

- **Unit tests** (mocked, no hardware needed): `PowerControlError` handling,
  `DeviceWatchdog`'s failure-counting and heartbeat-tick trip logic,
  recovery-cycle sequencing (disconnect → power_cycle → poll → reconnect)
  with a fake `scan_meshtastic_devices()` and fake `BasePowerControl`.
- **Manual verification against real hardware** (required before closing
  26.2/26.7): deliberately wedge a device (per Issue 12's rapid
  connect/disconnect repro), confirm `check_alive()` returns `False`,
  confirm a full recovery cycle reconnects successfully, and time how long
  re-enumeration takes.
- **Regression check**: existing `tests/test_server_receiver.py`,
  `tests/test_client_sender.py`, `tests/test_meshtastic_serial_transport.py`
  suites still pass unchanged (this epic only adds new methods/modules, no
  existing behavior changes).

---

## Implementation Order (Recommended)

1. Story 26.1 (power_control.py) + Story 26.3 (serial_number in scan) —
   independent, no hardware needed, low risk
2. Story 26.2 (check_alive) — needs early real-hardware smoke test to
   validate the chosen liveness call before building the watchdog around it
3. Story 26.4 (DeviceWatchdog) — the core orchestration, heaviest test coverage
4. Story 26.5 (server wiring) — first real integration point
5. Story 26.6 (client wiring) — same pattern, second integration point
6. Story 26.7 (DIY relay) — only if uhubctl testing in step 1-2 comes back negative
