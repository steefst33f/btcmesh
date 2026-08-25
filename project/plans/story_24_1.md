# Story 24.1: Update project docs with final implementation

## Context

EPIC 3 (Architecture Refactoring), EPIC 5 (Device Power-Cycle Recovery /
Watchdog), EPIC 6 (Device ID in GUI dropdowns), EPIC 7 (Reliability
Hardening), and EPIC 8 (Busy Indicator) are all complete in code, but the
project docs still describe an older state:

- `project/architecture.md` frames the `core/`/`transport/`/`client/`/`server/`
  split as a **future recommendation** ("Current vs Recommended", a
  "Migration Path" with unstarted phases) - it's all implemented now, and
  its illustrative code examples had drifted from the real method
  signatures and the pre-Story-20.4 wire format.
- `README.md`'s project structure tree predates several modules
  (`core/device_watchdog.py`, `core/transaction_history.py`,
  `transport/power_control.py`, `server/run_loop.py`, `gui/gui_common.py`),
  plus the `hardware/`, `data/`, and `scripts/hw_tests/` directories, and
  says nothing about the transaction-history or automatic device-recovery
  features.
- `project/tasks.txt` lists Story 24.1 itself as the only remaining open
  item in the Architecture Refactoring section (besides 24.2, the Swift
  skeleton, which stays out of scope here - no Swift code exists yet).

This story is a docs-only sync - no code changes. `unity-app/` was checked
and found untracked/empty-of-source (just a stray local CMake `build/`
dir) - not part of this project, left alone and undocumented.

## Scope (files touched)

1. **`project/architecture.md`** - reframe from "recommended future" to "as
   implemented": drop the Current-vs-Recommended framing and the Migration
   Path phases (all done), keep the layer-responsibility explanations and
   Swift section (still forward-looking and accurate), add the
   watchdog/power-control pieces as a real layer next to Transport, note
   `gui/gui_common.py` and `server/run_loop.py` as shared-orchestration
   additions, and correct several illustrative code snippets/tables that
   no longer matched the real API or wire format.
2. **`README.md`** - update the Project Structure tree (transport/, client/,
   server/, gui/, hardware/, data/, scripts/hw_tests/), add a short
   Features/section mention of transaction history and automatic device
   recovery (operator-facing, since it's a real shipped capability an
   operator running the relay would want to know about).
3. **`project/tasks.txt`** - mark Story 24.1 `[x]` with a short completion
   note, per this repo's convention of updating status inline as part of
   the fix rather than as a follow-up.

`project/protocol_spec.md` was checked against `core/protocol.py` /
`core/message_types.py` and found accurate (wire format hasn't changed
since Story 20.4) - left untouched.

## Verification

No tests apply (docs only). Verification is a read-through diff of each
file against the actual current code (already done during research).
