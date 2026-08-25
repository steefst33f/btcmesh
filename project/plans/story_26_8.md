# Story 26.8 Implementation Plan: Session-Aware check_alive() Timeout

## Context

**Why this change:**
Issue 46 (2026-08-24, see `project/issues.txt`) found and fixed
`check_alive()` (`transport/meshtastic_serial.py`) inheriting the
meshtastic library's default 300-second reply timeout instead of the
~20s its own docstring already claimed — `MeshtasticSerialTransport.connect()`
never passed an explicit `timeout=` when constructing its
`SerialInterface`, so `waitForAckNak()` silently used the interface's
huge default. Real-hardware confirmed via `sudo py-spy dump` mid-stall:
a single liveness check could block `DeviceWatchdog.tick()` for up to 5
minutes against a genuinely dead device. The fix pins `check_alive()`
to a fixed, explicit ~20s bound (`_CHECK_ALIVE_TIMEOUT_SECONDS`),
unconditionally, every time it's called.

Discussing that fix, a real trade-off the fixed 20s bound doesn't
account for came up: `DeviceWatchdog._recover()`'s own cooldown
(`recovery_cooldown_seconds`, default 60s) already throttles how often
an actual recovery *attempt* can run — but `check_alive()`'s timeout
controls how quickly each individual liveness *check* fails. A shorter
timeout means more checks complete (and fail) within a given period,
so during a genuinely prolonged outage with no active session and
nobody watching, the watchdog now logs "Device appears wedged"/attempts
recovery roughly every ~60-80s (`heartbeat_interval_seconds` + ~20s
check) instead of the old ~300-360s cadence - a real 3-5x increase in
Activity Log noise for that specific scenario, even though nothing is
actually going wrong beyond an already-known, ongoing outage.

**Goal:** make `check_alive()`'s timeout session-aware — short (~20s)
while a chunked transfer is actively in flight (the scenario Issue 46
actually needed fixed: every second the check blocks directly eats
into whether the transfer can complete before the client's own retry
budget runs out), long (~300s, matching the original de-facto
behavior, now made intentional rather than accidental) while idle, to
avoid unnecessary log noise when nothing time-sensitive is happening.

**Outcome:** `DeviceWatchdog.tick()` accepts a `session_active: bool`
telling it which of two configured timeouts to use for that check;
`server/run_loop.py`'s `run_polling_loop()` — the one piece that
already knows about sessions via `receiver.get_active_sessions()` — is
the sole bridge between the two concepts. `DeviceWatchdog` itself stays
completely ignorant of what a "session" is, matching its existing
transport-agnostic design.

---

## Current flow

```
server/run_loop.py: run_polling_loop()
  └─ watchdog.tick(now)                        # core/device_watchdog.py
       └─ (every heartbeat_interval_seconds)
            └─ transport.check_alive()          # transport/meshtastic_serial.py
                 └─ Timeout(maxSecs=_CHECK_ALIVE_TIMEOUT_SECONDS=20.0)
                     .waitForAckNak(...)
                     # ^ always 20s, regardless of whether a session is active
```

## New flow

```
server/run_loop.py: run_polling_loop()
  └─ watchdog.tick(now, session_active=bool(receiver.get_active_sessions()))
       └─ (every heartbeat_interval_seconds)
            └─ transport.check_alive(timeout_seconds=<20.0 if session_active else 300.0>)
                 └─ Timeout(maxSecs=timeout_seconds).waitForAckNak(...)
```

`receiver.get_active_sessions()` is already called every loop iteration
for the GUI's "Active Sessions" panel (`on_tick`) - `run_polling_loop()`
just also passes its truthiness into `watchdog.tick()`, no new query
needed.

---

## Architecture overview

- `DeviceWatchdog` stays transport-agnostic and stays ignorant of
  "sessions" as a concept, matching its existing design principle
  (only depends on `BaseTransport`/`BasePowerControl` - see its module
  docstring). It gains two configurable timeout values and a plain
  boolean parameter on `tick()`, decided entirely by the caller.
- `MeshtasticSerialTransport.check_alive()` gains an optional
  `timeout_seconds` parameter, falling back to its existing
  `_CHECK_ALIVE_TIMEOUT_SECONDS` default when omitted - existing
  callers/tests that don't pass it keep working unchanged.
- `BaseTransport.check_alive()`'s abstract signature is updated to
  match.
- `server/run_loop.py`'s `run_polling_loop()` is the only piece that
  actually knows about sessions (already calls
  `receiver.get_active_sessions()`) - the natural, sole bridge between
  the two concepts.

---

## Implementation steps

1. **`transport/base.py`** - update the abstract `check_alive()`
   signature to accept `timeout_seconds: Optional[float] = None`.
2. **`transport/meshtastic_serial.py`** -
   `check_alive(self, timeout_seconds: Optional[float] = None)`: use
   `timeout_seconds if timeout_seconds is not None else self._CHECK_ALIVE_TIMEOUT_SECONDS`
   when constructing the `Timeout`.
3. **`core/device_watchdog.py`**:
   - `DeviceWatchdog.__init__` gains `active_check_timeout_seconds: float = 20.0`
     and `idle_check_timeout_seconds: float = 300.0` - explicit on the
     watchdog itself (rather than reaching into the transport's
     private constant) so the values are self-documenting and directly
     testable.
   - `tick(self, now: float, session_active: bool = False) -> None` -
     picks the appropriate timeout and passes it through:
     `self._transport.check_alive(timeout_seconds=self._active_check_timeout_seconds if session_active else self._idle_check_timeout_seconds)`.
4. **`server/run_loop.py`** - in `run_polling_loop()`'s loop body:
   `watchdog.tick(now, session_active=bool(receiver.get_active_sessions()))`.
5. **Tests**:
   - `tests/test_meshtastic_serial_transport.py`: extend
     `TestMeshtasticSerialTransportCheckAlive` with a case asserting an
     explicit `timeout_seconds` argument is honored (passed straight
     to `Timeout(maxSecs=...)`), and that omitting it still falls back
     to the existing default (regression coverage for Issue 46).
   - `tests/test_device_watchdog.py`: extend `tick()` tests to assert
     `transport.check_alive()` is called with the short timeout when
     `session_active=True` and the long one when `False`/omitted.
   - Server run-loop tests (wherever `run_polling_loop()` is currently
     covered): assert `watchdog.tick()` receives `session_active=True`
     when `receiver.get_active_sessions()` is non-empty, `False` when
     empty.

---

## Critical files

| File | Change |
|---|---|
| `transport/base.py` | Abstract `check_alive()` signature gains `timeout_seconds` |
| `transport/meshtastic_serial.py` | `check_alive()` honors an explicit `timeout_seconds`, defaulting to the existing constant |
| `core/device_watchdog.py` | `tick()` gains `session_active`; picks active/idle timeout accordingly |
| `server/run_loop.py` | Passes `bool(receiver.get_active_sessions())` into `watchdog.tick()` |
| `tests/test_meshtastic_serial_transport.py`, `tests/test_device_watchdog.py`, server run-loop tests | New coverage for the above |

---

## Key design decisions

- **Why not give `DeviceWatchdog` direct access to session state?**
  Would cross the same layering boundary CLAUDE.md's architecture
  explicitly separates (`core/`'s pure logic vs. `server/`'s
  orchestration) - `DeviceWatchdog` already deliberately knows nothing
  about the BTCMesh protocol, reassembly, or sessions; only
  `BaseTransport`/`BasePowerControl`. Keeping `tick()`'s new parameter
  a plain boolean (not a session count/list) preserves that: the
  watchdog only ever learns "should I hurry," never anything
  protocol-specific.
- **Why keep the idle default at 300s specifically, rather than
  picking a fresh smaller number?** Continuity: 300s was already the
  de-facto behavior for this codebase's entire history before Issue
  46 - nobody had ever actually observed it being a problem outside an
  active session. Making it the explicit, intentional idle-path value
  (rather than inventing a new number) preserves that already-proven
  behavior for the one case it was arguably fine for, while fixing the
  case (active session) it demonstrably wasn't.
- **Why a plain boolean rather than richer state** (e.g. how many
  chunks are left, how close to the client's own timeout)? No evidence
  the extra precision would change behavior meaningfully - the binary
  distinction (something time-sensitive is happening right now vs.
  not) is the one that actually matters for the trade-off being
  solved. Can be revisited if real-hardware testing shows the binary
  cut is too coarse.
- **Backward compatibility**: `timeout_seconds`/`session_active` both
  default to values that reproduce Issue 46's current fixed behavior
  (`timeout_seconds=None` -> existing 20s constant; `session_active=False`
  on `tick()` unless the caller opts in) - `btcmesh_server_cli.py`
  needs its own call site updated too (mirroring
  `run_polling_loop()`'s change, since the CLI shares the same
  `run_polling_loop()` entry point) for the fix to actually take
  effect there, but nothing breaks if a caller is missed - it just
  silently keeps today's fixed-20s behavior.

---

## Verification

- Full unit test suite (`python -m unittest discover -s tests -p 'test_*.py'`)
  green.
- Real-hardware: repeat the Issue 46 reproduction (deliberate
  Heltec+relay hub unplug mid-session) and confirm recovery still
  completes within the same fast (~20s-class) window as the current
  fix. Separately, leave the server idle (no active session) through a
  spontaneous or deliberate disconnect and confirm the Activity Log
  doesn't show the 60-80s-cadence "wedged" spam this story exists to
  avoid - a longer, ~300s-class gap between log lines is the
  expected/correct outcome for that case.

---

## Implementation Completion (2026-08-25)

**Status:** Implemented as planned, no deviations from the design.

- All 5 implementation steps done exactly as scoped:
  `transport/base.py`'s abstract `check_alive()` gained
  `timeout_seconds: Optional[float] = None`;
  `MeshtasticSerialTransport.check_alive()` honors it, falling back to
  `_CHECK_ALIVE_TIMEOUT_SECONDS`; `DeviceWatchdog.__init__` gained
  `active_check_timeout_seconds`/`idle_check_timeout_seconds`, and
  `tick()` gained `session_active: bool = False`, picking between them;
  `run_polling_loop()` passes
  `session_active=bool(receiver.get_active_sessions())`.
- **One implementation detail the plan didn't fully spell out**: the
  plan's "Current flow" section assumed `receiver.get_active_sessions()`
  was "already called every loop iteration" - true only for the GUI
  path (`on_tick` provided). The CLI path (`on_tick=None`) previously
  only called it inside the periodic `LIVENESS_LOG_INTERVAL_SECONDS`
  block, not every iteration. Since `watchdog.tick()` now needs
  `session_active` on *every* call regardless of `on_tick`,
  `run_polling_loop()` now calls `get_active_sessions()` unconditionally
  once per iteration and reuses that single result for `on_tick` (if
  given), the liveness log, and `watchdog.tick()` - simpler than the
  plan's separate CLI-update concern, since both CLI and GUI already
  share this one `run_polling_loop()` call site (confirmed via `grep` -
  `watchdog.tick()` has exactly one call site in the whole codebase).
  The extra per-second call is a cheap in-memory dict scan
  (`TransactionReceiver.get_active_sessions()` ->
  `TransactionReassembler.get_active_sessions_info()`), no I/O -
  negligible cost.
- Updated `tests/test_server_run_loop.py`'s
  `test_on_tick_omitted_does_not_call_get_active_sessions_every_iteration`
  (asserted the now-superseded old behavior) to assert the new one
  instead, plus added `test_watchdog_tick_receives_session_active_from_active_sessions`.
  Added `test_honors_explicit_timeout_seconds`/
  `test_omitting_timeout_seconds_falls_back_to_default` to
  `tests/test_meshtastic_serial_transport.py`, and three `session_active`
  cases to `tests/test_device_watchdog.py`'s `TestTick`.
- **Test results**: 853/853 tests pass (847 pre-existing + 6 new).
- **Cross-reference added to Issue 43** (`project/issues.txt`):
  reverting the idle-path timeout to ~300s means a Stop Server that
  coincides with an idle heartbeat check can again take ~300s-class
  time, not the ~60-90s the issue originally estimated (which assumed
  a flat ~20s bound) - an intended consequence of this story, not a
  new regression, so noted there to avoid future confusion.
- Real-hardware verification not yet performed as of this writeup -
  the unit-test coverage above exercises every branch
  (`session_active=True`/`False`/omitted, explicit `timeout_seconds`
  honored/omitted, CLI vs. GUI call patterns), but the plan's suggested
  live repro (deliberate hub unplug mid-session vs. idle) hasn't been
  run yet.
