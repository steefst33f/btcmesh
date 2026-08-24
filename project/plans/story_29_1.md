# Story 29.1 Implementation Plan: Non-Blocking Busy Indicator for Client GUI Background Operations

## Context

**Why this change:**
Issue 39 (`project/issues.txt`) found that three of the client GUI's
four brief background connect/probe operations give no visual
feedback beyond an easy-to-miss status-log line - only Send
(`_connect_with_retry()`, called from `on_send_pressed()`) currently
disables controls and shows clear "in progress" state. Device
scanning/identity-probing, the known-nodes fetch triggered by
selecting a device, and the manual "refresh known nodes" button all
block silently from the user's point of view.

**Explicit requirement from discussion (2026-08-24):** the fix must
**not** make these three operations block anything else the user could
otherwise do immediately - e.g. selecting a device by its raw port
before identity-probing finishes labeling it, or typing a destination
node ID by hand instead of waiting for the known-nodes dropdown to
populate. Extending the existing "disable button + placeholder text"
convention (as Send already does) was considered and explicitly
rejected for this reason - see the design-choice discussion this plan
follows from. The indicator must be purely informational.

**Goal:** add a small, reusable, non-blocking busy indicator widget,
shown at the three under-covered call sites while their background
work is in flight, without disabling `device_spinner`, `node_spinner`,
or `dest_input` at any point during that work. Send's existing full
control-disable behavior is unchanged - deliberately out of scope,
since it exists to prevent two concurrent sends racing, a different
problem from "avoid making the user wait."

---

## Current flow

```
_scan_devices()                          # btcmesh_client_gui.py:512
  └─ device_spinner.text = "Scanning..."  # only visual cue
  └─ scan_thread() → devices_found

_handle_result('devices_found', ...)      # :701
  ├─ 1 device  → device_spinner.text = <it>  → fires on_device_selected
  └─ N devices → probe_devices_in_background(devices, result_queue)
                    └─ pushes ('device_identity', path, id, name)
                       once per device, no "all done" signal at all

on_device_selected(spinner, text)         # :583
  └─ status_log: "Fetching device info and known nodes..."  # only cue
  └─ fetch_thread() → device_identity, known_nodes_fetched

on_refresh_nodes(instance)                # :643
  └─ status_log: "Fetching known nodes..."  # only cue
  └─ fetch_thread() → known_nodes_fetched
```

No widget is ever disabled at any of these three sites today - they're
already non-blocking by accident (nobody added a disable call), just
invisible.

## New flow

```
_scan_devices()
  └─ device_busy.start()
  └─ scan_thread() → devices_found

_handle_result('devices_found', ...)
  ├─ 1 device  → sets .text → on_device_selected starts its own busy
  │              indicators; device_busy.stop() runs too (ref-counted,
  │              see below) but on_device_selected's own start() keeps
  │              it visible until that fetch really finishes
  └─ N devices → probe_devices_in_background(...) [already device_busy]
                    └─ pushes device_identity per device, THEN a new
                       final ('device_probe_complete',) sentinel

_handle_result('device_probe_complete', ...)   # NEW
  └─ device_busy.stop()

on_device_selected(spinner, text)
  └─ device_busy.start() ; nodes_busy.start()   # both - one thread does both jobs
  └─ fetch_thread() → device_identity (stops device_busy),
                       known_nodes_fetched (stops nodes_busy)

on_refresh_nodes(instance)
  └─ nodes_busy.start()
  └─ fetch_thread() → known_nodes_fetched (stops nodes_busy)
```

`device_spinner`/`node_spinner`/`dest_input` are never touched by any
of the above - selection and manual typing remain available throughout.

---

## Architecture overview

- **New `BusyIndicator` class in `gui/gui_common.py`** (shared, so the
  server GUI could reuse it later if it ever wants the same thing) -
  a thin `Label`-based widget, reference-counted rather than a plain
  on/off flag:
  - `start()` increments an internal counter; if it was `0`, makes the
    label visible and schedules a `Clock.schedule_interval` that
    cycles its text through a few frames (e.g. `"Loading"`,
    `"Loading."`, `"Loading.."`, `"Loading..."`, repeating) - no new
    Kivy widget class beyond what's already used elsewhere in this
    codebase (`Label`), no canvas/graphics work.
  - `stop()` decrements the counter; only when it reaches `0` does it
    cancel the schedule and hide the label (empty text / minimal
    height).
  - Reference-counting (not a boolean) is the key piece that makes
    overlapping start/stop calls from different code paths safe - see
    Key Design Decisions.
- **Two instances in `btcmesh_client_gui.py`**: `self.device_busy`
  (placed near `device_spinner`/`refresh_btn`) and `self.nodes_busy`
  (placed near `node_spinner`/`refresh_nodes_btn`) - device-area work
  and known-nodes-area work are independent and can overlap, so one
  shared indicator would either hide which one is active or falsely
  imply only one thing is happening.
- **One small addition to `gui/gui_common.py`'s `probe_devices_in_background()`**:
  push a final `('device_probe_complete',)` sentinel after the loop,
  unconditionally (e.g. in a `finally`), so `_handle_result()` has a
  reliable "the whole batch is done" signal - today there is none,
  which the busy indicator's `stop()` call needs.

---

## Implementation steps

1. **`gui/gui_common.py`**: add `BusyIndicator(Label)` with
   `start()`/`stop()` as described above. Keep it minimal - no
   constructor arguments beyond normal `Label` kwargs; the cycling
   message text is a `start(message: str = "Loading")` parameter so
   callers can customize it per call site if useful.
2. **`gui/gui_common.py`**: `probe_devices_in_background()` - push
   `('device_probe_complete',)` once after the `for device in
   list(devices):` loop finishes, regardless of how many devices were
   skipped/probed.
3. **`btcmesh_client_gui.py`** UI build: instantiate `self.device_busy`
   and `self.nodes_busy`, add them to the layout near their respective
   spinners (small, low-visual-weight - this is a secondary cue, not a
   dialog/overlay).
4. **`_scan_devices()`** (`:512`): `self.device_busy.start()` right
   before `threading.Thread(...).start()`.
5. **`_handle_result()`** (`:695`): in the `devices_found` branch,
   call `self.device_busy.stop()` at both the single-device and
   no-devices exit paths (multi-device path leaves it running -
   `probe_devices_in_background` was just started and owns stopping
   it). Add a new `device_probe_complete` branch calling
   `self.device_busy.stop()`.
6. **`on_device_selected()`** (`:583`): `self.device_busy.start()` and
   `self.nodes_busy.start()` right before `threading.Thread(...).start()`.
   In `_handle_result()`'s existing `device_identity` branch, call
   `self.device_busy.stop()`; in the existing `known_nodes_fetched`
   branch, call `self.nodes_busy.stop()`.
7. **`on_refresh_nodes()`** (`:643`): `self.nodes_busy.start()` before
   `threading.Thread(...).start()`; already covered by the
   `known_nodes_fetched` branch's `self.nodes_busy.stop()` added in
   step 6 (same result type, same stop call - no special-casing
   needed).
8. **No changes** to `on_send_pressed()`/`_connect_with_retry()`/
   `_set_controls_enabled()` - confirmed out of scope.

---

## Critical files

| File | Change |
|---|---|
| `gui/gui_common.py` | New `BusyIndicator` class; `probe_devices_in_background()` gains a completion sentinel |
| `btcmesh_client_gui.py` | Two `BusyIndicator` instances wired into `_scan_devices()`, `on_device_selected()`, `on_refresh_nodes()`, and `_handle_result()`'s `devices_found`/`device_identity`/`known_nodes_fetched`/new `device_probe_complete` branches |
| `tests/test_gui_common.py` | New tests for `BusyIndicator` (start/stop, reference counting) and the new completion sentinel from `probe_devices_in_background()` |
| `tests/test_btcmesh_client_gui.py` | New/extended tests asserting start/stop calls happen at the right points, **and** a regression test asserting `device_spinner.disabled`/`node_spinner.disabled`/`dest_input.disabled` stay `False` throughout each of the three call sites |

---

## Key design decisions

- **Reference-counted start/stop, not a boolean flag**: `on_device_selected`
  can fire in a way that overlaps with `_scan_devices`'s own
  `device_busy` usage (the single-device auto-select path sets
  `device_spinner.text`, which synchronously triggers
  `on_device_selected` - see the existing code comment at
  `btcmesh_client_gui.py:709-718`). A plain boolean would let one
  code path's `stop()` prematurely hide the indicator while another
  path's work is still genuinely in flight. Counting "how many reasons
  to be visible are currently open" instead makes every call site's
  start/stop pair independently correct regardless of what else is
  happening concurrently.
- **Two indicators, not one**: device-area and known-nodes-area work
  are independent (e.g. `on_refresh_nodes` can run while device
  scanning from a fresh `on_refresh_devices()` press is also
  happening) - a single shared indicator can't represent "two
  different things are loading" without becoming ambiguous.
- **Why not disable anything**: explicit, direct requirement from
  discussion - the results of these three background operations are
  conveniences (a nicer label, a prefilled dropdown), not
  preconditions for anything the user might want to do next. Blocking
  on them would regress UX for a user who already knows the device
  path or destination node ID.
- **Why a custom label-cycling widget rather than `kivy.uix.progressbar.ProgressBar`**:
  no widget beyond `Label`/`Button`/`Spinner`/`TextInput`/`ScrollView`
  is used anywhere in this codebase today (`gui/gui_common.py`,
  `btcmesh_client_gui.py`, `btcmesh_server_gui.py`) - a text-cycling
  `Label` matches that existing minimal-widget convention and needs no
  new graphics/animation code, while still being genuinely visible and
  distinct from a static log line.
- **`probe_devices_in_background()`'s missing completion signal**: not
  scope creep - the busy indicator's `stop()` call for the
  multi-device probe path has no other reliable trigger today (the
  function currently has no notion of "done," only per-device
  progress), so this is a required, minimal addition for the feature
  to work correctly at all, not an unrelated improvement bundled in.
- **Send's behavior is explicitly unchanged**: starting a second
  concurrent send while one is in flight is a real correctness/safety
  concern (two overlapping `TransactionSender` runs against one
  transport), not merely "the user has to wait" - a fundamentally
  different problem from the three call sites this story addresses,
  and the discussion that shaped this plan didn't ask for it to
  change.

---

## Verification

- Full unit test suite (`python -m unittest discover -s tests -p 'test_*.py'`)
  green, including the new `BusyIndicator` tests and the
  non-blocking-regression assertions.
- Manual, real hardware: trigger a device scan with multiple devices
  attached and confirm (a) the device-area indicator appears and
  disappears at the right times, and (b) the device dropdown remains
  selectable throughout, including selecting a device before
  identity-probing has finished labeling it. Repeat for known-nodes
  fetch (via device selection and via the manual refresh button),
  confirming `dest_input` stays typable and `node_spinner` stays
  selectable throughout.
