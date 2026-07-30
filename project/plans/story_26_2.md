# Story 26.2 Implementation Plan: `check_alive()` liveness check

## Context

**Why this change:**
EPIC 5 (Device Power-Cycle Recovery/Watchdog, see `project/plans/story_26_1.md`)
needs a way to detect that a Meshtastic device is genuinely wedged (Issue
12/16) before `DeviceWatchdog` (Story 26.4) attempts a recovery power-cycle.
The epic plan flagged this as its first Open Question, since it can't be
answered from reading code alone: does a candidate liveness call actually
fail against a wedged device, or does it just return stale cached data
regardless of real responsiveness?

**This was resolved empirically this session, against a genuinely wedged
device** (reproduced by rapidly toggling a device's DTR/RTS lines via
`pyserial` until it got stuck mid-boot - matching Issue 12's original
"stuck mid-boot from rapid repeated connect/disconnect cycles" symptom
exactly, confirmed via a real `connect()` timing out after ~31s). Three
candidates were tested directly against it:

- **`getMyNodeInfo()`** (the epic plan's original guess) — confirmed to be
  a pure in-memory dict lookup (`self.nodesByNum.get(...)`), populated once
  at initial handshake. **No live check at all.**
- **`sendHeartbeat()` and raw `stream.write()`** — both **returned
  successfully in ~0ms even against the wedged device**. USB writes are
  buffered by the OS regardless of whether firmware actually processes
  them - fire-and-forget calls cannot detect this failure mode.
- **`Node.getMetadata()`** (a local admin "get device metadata" request,
  via `iface.waitForAckNak()`, default ~20s bounded timeout) — **the one
  candidate that actually works**: returned in <1s against a healthy
  device, and genuinely raised `MeshInterfaceError("Timed out waiting for
  an acknowledgment")` after ~20s against the wedged device. This is a
  real local round-trip (request + waited acknowledgment), not just a
  write.

**One complication:** `getMetadata()`'s response handler unconditionally
`print()`s firmware/hardware info to stdout on every successful call -
fine for interactive CLI use, unwanted noise from a periodic background
health check. Redirecting stdout globally around the call was considered
and rejected: stdout redirection is global process state, and this will
be called periodically from a background watchdog thread (Story 26.4)
while the main thread does other work - a real interference risk.
**Decision: reimplement the same request with our own quiet response
handler** (confirmed working, no print, real ack, <1s round-trip on the
healthy device) rather than call the public `getMetadata()` directly.

**Goal/Outcome:** `check_alive()` added to `BaseTransport` and implemented
in `MeshtasticSerialTransport` using this proven mechanism - a genuine,
bounded, real liveness signal for `DeviceWatchdog` to build on.

---

## Reproducing a Wedged Device (for testing)

Story 26.4's `DeviceWatchdog` and its recovery-cycle tests will also need
a genuinely wedged device to test against, so the working recipe is
recorded here rather than left as a one-off.

**What didn't work** (all tried first, none wedged the device):
- 25 clean `connect()`/`disconnect()` cycles in a row (~3.3s each).
- 60 rapid raw `pyserial` port open/close cycles (open, sleep 0.05s, close).
- 10 cycles of starting a real `meshtastic.serial_interface.SerialInterface`
  handshake in a thread and forcibly `close()`-ing it ~0.8s in (before the
  ~3.3s handshake would normally complete).

**What worked** — rapidly toggling DTR/RTS directly via `pyserial`, which
is what many USB-serial/native-USB boards use to trigger a hardware reset
(the same mechanism Arduino-style auto-reset circuits use), interrupting
the device's boot sequence mid-way:

```python
import serial
import time

port = "<meshtastic device's serial port>"
s = serial.Serial(port, 115200, timeout=0.1)
for i in range(200):
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.01)
    s.setDTR(True)
    s.setRTS(False)
    time.sleep(0.01)
s.close()
```

On the native-USB ESP32-S3 board used for this test, the OS-level write
actually failed partway through with `OSError: [Errno 6] Device not
configured` (the whole USB endpoint dropped and came back) - a strong
signal it had actually reset. The device re-enumerated under a **different,
more generic path** than its usual serial-number-based one (e.g.
`/dev/cu.usbmodem21401` instead of `/dev/cu.usbmodem983DAEE5AB3C1`), which
in hindsight was itself a useful tell that something was off. A subsequent
real `connect()` attempt to that path then genuinely timed out after
~31s with `"Timed out waiting for connection completion"` - matching
Issue 12's original symptom exactly.

**Recovery**: the device stayed wedged and required a physical
unplug/replug - there was no software power-cycle path wired to it in
this session (Story 26.7's relay was wired to the *other* test device).
Anyone repeating this on a device that already has a Story 26.7 relay
attached should be able to recover it with `power_cycle()` instead.

---

## Implementation

### `transport/base.py`

Add as a new abstract method:

```python
@abstractmethod
def check_alive(self) -> bool:
    """Best-effort liveness check. Returns False (never raises) if not
    connected or the device doesn't respond within a bounded timeout."""
    ...
```

This is a breaking change for any concrete `BaseTransport` subclass -
only `MeshtasticSerialTransport` exists in the main codebase; `Mock(spec=
BaseTransport)` usages in `tests/test_server_receiver.py`/
`tests/test_client_sender.py` are unaffected (mocks don't enforce ABC
completeness), but `StubTransport` in `tests/test_transport_base.py`
needs `check_alive()` added (simple, matching its existing minimal style).

### `transport/meshtastic_serial.py`

```python
def check_alive(self) -> bool:
    """Best-effort liveness check. Returns False (never raises) if not
    connected or the device doesn't respond within the library's default
    timeout (~20s).

    Sends a local admin "get device metadata" request and waits for a
    real round-trip acknowledgment - proven by real hardware testing
    (see project/plans/story_26_2.md) to be the only reliable signal:
    getMyNodeInfo() only reads an in-memory cache, and sendHeartbeat()/
    raw writes return successfully even against a genuinely wedged
    device, since the OS buffers the write regardless of whether
    firmware actually processes it.

    Deliberately reimplements node.Node.getMetadata() rather than
    calling it directly: its response handler unconditionally prints
    firmware/hardware info to stdout, which we don't want firing from a
    periodic background health check, and globally redirecting stdout
    around the call would be unsafe once this runs on a background
    watchdog thread (Story 26.4) alongside other console/log output.
    """
    if self._iface is None:
        return False
    try:
        from meshtastic import admin_pb2

        def _quiet_response_handler(p):
            if "routing" in p["decoded"]:
                if p["decoded"]["routing"]["errorReason"] != "NONE":
                    self._iface._acknowledgment.receivedNak = True
            else:
                self._iface._acknowledgment.receivedAck = True

        p = admin_pb2.AdminMessage()
        p.get_device_metadata_request = True
        self._iface.localNode._sendAdmin(
            p, wantResponse=True, onResponse=_quiet_response_handler
        )
        self._iface.waitForAckNak()
        return True
    except Exception:
        return False
```

This relies on a few non-public (`_`-prefixed) `meshtastic` internals
(`_sendAdmin`, `_acknowledgment`), which is a deliberate, documented
tradeoff — flagged as a fragility risk (a future `meshtastic` library
upgrade could change these without notice) in Key Design Decisions below.

---

## Critical Files

| File | Change |
|------|--------|
| `transport/base.py` | Add `check_alive()` abstract method |
| `transport/meshtastic_serial.py` | Implement `check_alive()` (quiet metadata round-trip) |
| `tests/test_transport_base.py` | Add `check_alive()` to `StubTransport` |
| `tests/test_meshtastic_serial_transport.py` | New tests for `check_alive()` |
| `project/plans/story_26_1.md` | Mark Open Question #1 resolved |

---

## Key Design Decisions

1. **Reimplement the admin request quietly, don't call `getMetadata()`
   directly** — avoids both the unwanted `print()` output and the
   thread-safety risk of globally redirecting stdout from a background
   watchdog thread. Confirmed working via direct real-hardware testing.
2. **Relies on non-public `meshtastic` internals** (`_sendAdmin`,
   `_acknowledgment`) — accepted tradeoff since no public equivalent
   exists without the print side effect. Risk: a future library version
   could rename/change these. Mitigation: the unit tests mock these
   internals (so they won't catch an upstream break), but this is
   exactly the kind of thing to notice quickly via the existing manual
   real-hardware verification habit this project already uses before
   trusting new watchdog behavior in Story 26.4/26.5/26.6.
3. **No custom timeout parameter** — keeps `check_alive()`'s signature
   matching the epic plan's original parameterless sketch and relies on
   the library's own bounded default (~20s). Only the unhealthy case
   blocks that long; the healthy case returns in under a second (measured
   in real testing). If a shorter/configurable timeout is needed later,
   `DeviceWatchdog` (Story 26.4) can wrap this call in its own bounded
   thread/executor rather than plumbing a timeout parameter through the
   whole interface now (YAGNI).
4. **Thread-safety of calling this concurrently with normal send/receive
   traffic on the same `_iface` is out of scope for this story** — Story
   26.4 is where `check_alive()` actually gets invoked periodically from
   a background thread, and is the right place to decide whether that
   needs a lock around shared `_iface` access.

---

## Verification

- **Real hardware** (already done, this session, ahead of implementation):
  reproduced a genuinely wedged device (DTR/RTS toggle stress until a
  real `connect()` timed out after ~31s matching Issue 12's original
  symptom), and confirmed the quiet metadata-request mechanism returns
  successfully (<1s) against a healthy device and fails
  (`MeshInterfaceError` after ~20s) against the wedged one.
- **Unit tests** (mocked `_iface`/`localNode`, no hardware): `check_alive()`
  returns `False` when not connected; returns `True` when the quiet
  request succeeds without raising; returns `False` on any exception
  (including a simulated `MeshInterfaceError` timeout); asserts **no
  stdout output** occurs (capture stdout during the call and assert it's
  empty) - a concrete, testable proxy for "doesn't call the noisy public
  `getMetadata()`."
- **Regression check**: full suite (`python -m unittest discover -s tests
  -p 'test_*.py'`) still passes, including the updated `StubTransport`.
