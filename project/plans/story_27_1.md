# Story 27.1-27.3 Implementation Plan: Node ID Display in Device Dropdowns

## Context

**Why this change:**
Both GUIs' device dropdowns only show OS-level serial port paths (e.g.
`/dev/cu.usbserial-0001`) - not the Meshtastic node ID, which is a
protocol-level identity you can only learn by actually connecting.
Anyone with more than one Meshtastic device attached has to remember (or
re-discover, by connecting and checking) which physical device is on
which port. This surfaces that identity directly in the dropdown.

**Scope - both GUIs, via a shared helper**: the client GUI's device
spinner and the server GUI's Story 18.2 device settings spinner have the
exact same limitation, both built on `scan_meshtastic_devices()`'s path
list. Per this project's "no duplicated logic" principle, the
peek-connect-and-get-node-id logic belongs in `core/meshtastic_utils.py`
(Story 27.1), not copy-pasted into each GUI file (Stories 27.2/27.3).

**No lighter-weight lookup exists**: `MeshtasticSerialTransport.connect()`
needs a real handshake (`iface.connect()` + `iface.waitForConfig()`,
~5s on a healthy device) before `local_node_id` is populated - there's
no "just peek the node ID" call in the underlying Meshtastic library.
Getting a node ID genuinely means connecting, reading it, and
disconnecting again.

**When to look it up**: two simpler options were considered and rejected.
Blocking the scan itself (peek-connecting to every candidate serially
before showing anything) would make an already-not-instant scan
meaningfully slower, and a false-positive candidate - e.g. the Story
26.7 relay board, which can show up in scan results since
`scan_meshtastic_devices()` filters by a VID blacklist, not a whitelist -
would fail slowly, on the order of the same ~30s worst-case connect
timeout documented in `project/plans/story_26_2.md`. Fully lazy
(look up only on selection) wouldn't actually solve the stated problem
either - you'd still have to connect to each device in turn to find out
which is which. Landed on **background progressive fill** instead: the
dropdown appears immediately with paths only (today's behavior,
unchanged), then a background thread probes each device in turn and
each entry's label updates in place as its node ID resolves - no
blocking, no extra clicks.

---

## Design

### Story 27.1 - `core/meshtastic_utils.py`

```python
def probe_device_node_id(path: str) -> Optional[str]:
    """Briefly connect to a candidate serial port to learn its Meshtastic
    node ID, then disconnect. Returns None (never raises) if the path
    isn't a genuine Meshtastic device, is already in use, or the
    connection attempt fails/times out - e.g. a false-positive candidate
    from scan_meshtastic_devices()'s VID-blacklist filtering, such as the
    Story 26.7 relay board's own serial port, which speaks a completely
    different protocol.

    Lazy-imports MeshtasticSerialTransport (matching this module's
    existing dependency style) to avoid a hard import-time dependency
    from core/ on transport/.
    """
    from transport.meshtastic_serial import MeshtasticSerialTransport
    from transport.base import TransportConnectionError

    transport = MeshtasticSerialTransport()
    try:
        transport.connect(path)
        return transport.local_node_id
    except TransportConnectionError:
        return None
    finally:
        transport.disconnect()
```

Also add a small formatting helper, mirroring `format_node_display()`:

```python
def format_device_display(path: str, node_id: Optional[str]) -> str:
    """'path' alone if node_id isn't known yet/unavailable, else
    'path (node_id)' - e.g. '/dev/cu.usbserial-0001 (!7c5b4418)'."""
    return f"{path} ({node_id})" if node_id else path
```

### Stories 27.2/27.3 - GUI wiring (client and server GUIs, same shape)

Both GUIs already maintain a raw-data-list-plus-formatted-display-list
pattern for an almost identical problem - the client GUI's known-nodes
dropdown (`self.known_nodes` + `format_node_display()` +
`on_node_selected()`'s reverse lookup by matching display text back to
the underlying dict). This reuses that exact shape for devices instead
of introducing a new pattern:

```python
self.devices = []  # type: list[dict]  # [{'path': ..., 'node_id': None}, ...]
```

On scan completion (existing `'devices_found'` handling), build
`self.devices` from the raw path list (`node_id: None` for all, exactly
today's behavior at this point) and set
`spinner.values = [format_device_display(d['path'], d['node_id']) for d in self.devices]`
- visually identical to today until lookups start resolving.

Then kick off one background thread that probes each device in turn and
pushes a result per device:

```python
def _probe_device_node_ids(self):
    def probe_thread():
        for device in list(self.devices):
            if device['path'] == <currently-connected path, if any>:
                continue  # already known from the live connection - no redundant probe
            node_id = probe_device_node_id(device['path'])
            self.result_queue.put(('device_node_id', device['path'], node_id))
    threading.Thread(target=probe_thread, daemon=True).start()
```

New `_handle_result()` branch:

```python
elif result[0] == 'device_node_id':
    path, node_id = result[1], result[2]
    for device in self.devices:
        if device['path'] == path:
            device['node_id'] = node_id
            break
    self._refresh_device_spinner_labels()  # rebuild spinner.values from self.devices,
                                            # preserving spinner.text's underlying selection
```

`on_device_selected`/the server GUI's "read the spinner text at start"
call sites resolve the underlying path by reverse lookup (matching
`on_node_selected`'s existing pattern):

```python
def _device_path_from_display(self, text: str) -> Optional[str]:
    for device in self.devices:
        if format_device_display(device['path'], device['node_id']) == text:
            return device['path']
    return text  # fall back to treating it as a raw path (e.g. special
                 # sentinel values like "Auto-detect" that aren't in self.devices)
```

`_refresh_device_spinner_labels()` must preserve the *currently selected*
device across a label change (relabeling shouldn't silently reset the
user's selection) - re-set `spinner.text` to the new formatted label for
whichever device it currently resolves to, immediately after updating
`spinner.values`.

---

## Critical Files

| File | Change |
|------|--------|
| `core/meshtastic_utils.py` | Add `probe_device_node_id()`, `format_device_display()` |
| `btcmesh_client_gui.py` | `self.devices` list state, background probe thread, `device_node_id` result handling, spinner relabeling, `on_device_selected` reverse lookup |
| `btcmesh_server_gui.py` | Same pattern applied to its device settings spinner (Story 18.2 code path) |
| `tests/test_meshtastic_utils.py` | Tests for `probe_device_node_id()` (success, failure/timeout → `None`) and `format_device_display()` |
| `tests/test_btcmesh_client_gui.py` | Tests for background fill-in, currently-connected device skipped, selection resolves correct path |
| `tests/test_btcmesh_server_gui.py` | Same, for the server GUI's device spinner |
| `project/tasks.txt` | Mark Stories 27.1-27.3 done once complete |

---

## Key Design Decisions

1. **Background progressive fill, not blocking the scan or fully lazy** -
   the two simpler alternatives were both explicitly considered and
   rejected: blocking the scan would make an already-multi-second
   operation noticeably slower (and vulnerable to a false-positive
   candidate's ~30s worst-case connect timeout); fully lazy (only on
   selection) wouldn't actually solve the stated problem, since you'd
   still have to connect to each device in turn to learn its identity.
2. **Sequential probing, not parallel** - simpler and lower-risk for a
   first implementation (untested whether concurrent serial connects to
   different ports behaves reliably across platforms); worth revisiting
   only if the sequential fill-in feels too slow in practice with many
   devices attached.
3. **No custom timeout wrapper around each probe** - `MeshtasticSerialTransport.connect()`
   already fails/times out on its own (documented ~30s worst case
   against a non-responsive port); since probing is entirely
   background/non-blocking, that's an acceptable bound without extra
   engineering.
4. **Currently-connected device is never re-probed** - both to avoid a
   redundant ~5s connection attempt and to avoid any risk of conflicting
   with the transport already actively in use; its node ID is read
   directly from the live connection instead.
5. **Reuses the known-nodes dropdown's established display/reverse-lookup
   pattern** rather than inventing a new one, keeping the codebase
   consistent (`self.devices` + `format_device_display()` mirrors
   `self.known_nodes` + `format_node_display()`).

---

## Verification

- **Unit tests**:
  - `probe_device_node_id()`: returns the node ID on a successful mock
    connect; returns `None` (doesn't raise) when `connect()` raises
    `TransportConnectionError`.
  - `format_device_display()`: `'path'` when `node_id` is `None`,
    `'path (node_id)'` otherwise.
  - Client/server GUI: scan populates `self.devices` with `node_id: None`
    initially and unlabeled spinner values; a `device_node_id` result
    updates the matching device and relabels the spinner; the
    currently-connected device's path is excluded from the probe loop;
    selecting a labeled entry resolves to the correct underlying path.
- **Regression check**: full suite still passes; existing device-scan
  and device-selection tests still pass unchanged where they only assert
  path-based behavior (server GUI's `DEVICE_AUTO_DETECT` sentinel and
  similar special values must still round-trip correctly through the
  new reverse-lookup fallback).
- **Manual**: run both GUIs with 2+ real devices attached (e.g. reusing
  today's session's hardware setup - the CP2102-bridged device and the
  seeed-xiao-s3 board), confirm the dropdown shows paths immediately,
  node IDs fill in within a few seconds without any clicking, and
  selecting an entry connects to the right physical device.

---

## Story 27.2 Implementation Notes (client GUI)

Concrete integration into `btcmesh_client_gui.py`'s existing
`self.result_queue` + `_check_results` polling + `_handle_result` pattern.

**New state** (in `__init__`):
- `self.devices: list[dict]` - `[{'path': str, 'node_id': Optional[str]}, ...]`,
  rebuilt on every scan.
- `self._active_device_path: Optional[str]` - path of the device currently
  connecting or connected, so its node ID comes from the live connection
  instead of a redundant probe.

**`_handle_result`'s existing `devices_found` branch**, extended:
- Build `self.devices` from the raw path list (`node_id: None` for all).
- Single device found: auto-connect as today, and additionally set
  `self._active_device_path = devices[0]`. Deliberately do **not** kick off
  a background probe in this case - nothing to disambiguate, and the
  device is about to connect anyway, so its real node ID arrives a few
  seconds later via the `'connected'` result instead of a separate probe
  connection.
- Multiple devices found: unchanged selection-prompt behavior, plus kick
  off `_probe_device_node_ids()` in the background.

**New `_handle_result` branch for `'device_node_id'`** (one message per
device, pushed by the probe thread): update the matching entry in
`self.devices`, then call `_refresh_device_spinner_labels()`.

**`'connected'` handling** (existing block that does
`self.iface = action.store_iface`): additionally, if
`self._active_device_path` is set, update that device's `node_id` in
`self.devices` from `result[2]` and call `_refresh_device_spinner_labels()`
- this is what satisfies "currently-connected device is not re-probed, its
node ID comes from the live connection" without adding any explicit
skip-list to the probe loop itself.

**New methods**:
- `_probe_device_node_ids()`: spawns one daemon thread that calls
  `probe_device_node_id()` for every device in `self.devices` in turn,
  pushing `('device_node_id', path, node_id)` per device. No skip-list
  needed - by the time this runs (multi-device branch only), nothing is
  connected yet in this codebase's actual flow: `on_refresh_devices`
  always disconnects before rescanning, and the startup scan begins with
  no connection either.
- `_refresh_device_spinner_labels()`: rebuilds `device_spinner.values`
  from `self.devices`; resolves the currently-selected entry's path via
  `_device_path_from_display`, and re-sets `device_spinner.text` to that
  path's new formatted label. Unbinds/rebinds `on_device_selected` around
  the mutation (matching the existing pattern already used for
  `SELECT_DEVICE_TEXT`) so relabeling never fires a spurious reconnect.
- `_device_path_from_display(text)`: reverse lookup, mirroring
  `on_node_selected`'s existing pattern for known nodes - returns the
  matching device's path, or `text` itself unchanged as a fallback
  (covers the sentinel values `NO_DEVICES_TEXT`/`SCANNING_TEXT`/
  `SELECT_DEVICE_TEXT`, which are deliberately never in `self.devices`).

**`on_device_selected`** updated to resolve the path from the (possibly
node-ID-suffixed) display text before connecting:
```python
def on_device_selected(self, spinner, text):
    if text in (NO_DEVICES_TEXT, SCANNING_TEXT, SELECT_DEVICE_TEXT, ''):
        return
    path = self._device_path_from_display(text)
    self._disconnect_device()
    self._active_device_path = path
    self._init_meshtastic(port=path)
```

**`_disconnect_device()`**: reset `self._active_device_path = None`
alongside its existing state resets (order-safe because
`on_device_selected` re-sets it immediately after calling
`_disconnect_device()`).

**Edge cases considered, not specially handled** (consistent with the
plan's "no custom timeout/synchronization" stance):
- User selects a device while its background probe is still in flight:
  the probe's `connect()` and the selection's `connect()` can race for
  the same serial port. Worst case the probe attempt fails (port busy)
  and returns `None` for that entry, silently overwritten moments later
  by the real `'connected'` node ID anyway. No lock/cancellation added.
- Single device that fails to connect: its dropdown entry is never
  probed and stays path-only. Showing no node ID for an unreachable
  device is arguably correct, not a bug to route around.

Files touched: `btcmesh_client_gui.py`, `tests/test_btcmesh_client_gui.py`.

---

## Enhancement: Node Names + Dropdown Dedup (2026-08-22)

**Context**: real-hardware testing of Story 27.2 surfaced Issue 37
(`project/issues.txt`) - the Heltec's two OS-level path aliases both
show up as separate dropdown entries, since `eliminate_duplicate_port()`
doesn't recognize them as the same device. Discussed as part of that
issue: since `probe_device_node_id()` already opens a full connection
per candidate, it can grab the device's configured *name* at the same
time for free (`core.meshtastic_utils.get_own_node_name()` already
exists and reads it off the same `iface`) - and once every candidate's
node ID is known, any two paths that resolved to the *same* node ID are
provably the same physical device (node ID is a Meshtastic protocol
identity, not a USB/OS one), so the dropdown can collapse them into one
entry without needing to fix `eliminate_duplicate_port()` at all.

**Scope decision**: implement this as more commits on the still-open,
unmerged `story-27-1`/`story-27-2` branches (PRs #49/#50), not new
branches - it directly revises the same functions those PRs introduce
hours earlier the same day, in response to real-hardware findings from
verifying them. Server GUI (Story 27.3) hasn't started yet, so it
inherits this improved behavior from day one instead of needing its own
retrofit later.

**What this fixes vs. doesn't**: this collapses *display* duplicates
(the Heltec showing twice) using data already collected. It does **not**
reduce the underlying *probe cost* - every raw candidate path, including
ones that will turn out to be duplicates, still gets a full probe
connection each, because there's no way to know two paths are duplicates
*before* both have been probed and their node IDs compared. It also does
**not** touch the relay board's false-positive ports (Issue 37's other
half) - those never get a node ID at all, so nothing to dedupe against;
that still needs the separate VID/description pre-filter Issue 37
already proposes.

### Design

**`core/meshtastic_utils.py`**:

```python
@dataclass
class ProbedDevice:
    """Result of probing a candidate serial port: its Meshtastic node ID
    and, if available, its configured name. Fields are None (never a
    bare None return) if the path isn't a genuine/reachable Meshtastic
    device - callers never need a None-check before destructuring."""
    node_id: Optional[str]
    name: Optional[str]


def probe_device_identity(path: str) -> ProbedDevice:
    """Replaces probe_device_node_id() - same brief connect/disconnect,
    now also reading the node's configured name off the same iface
    before disconnecting (free: get_own_node_name() just reads data
    already delivered during the same handshake)."""
    from transport.meshtastic_serial import MeshtasticSerialTransport
    from transport.base import TransportConnectionError

    transport = MeshtasticSerialTransport()
    try:
        transport.connect(path)
        return ProbedDevice(
            node_id=transport.local_node_id,
            name=get_own_node_name(transport._iface),
        )
    except TransportConnectionError:
        return ProbedDevice(node_id=None, name=None)
    finally:
        transport.disconnect()
```

`format_device_display()` gains an optional `name` parameter:

```python
def format_device_display(path: str, node_id: Optional[str], name: Optional[str] = None) -> str:
    if node_id and name:
        return f"{name} ({node_id})"
    if node_id:
        return f"{path} ({node_id})"
    return path
```

**`btcmesh_client_gui.py`**:

- `self.devices` entries gain a `'name'` key:
  `{'path': ..., 'node_id': None, 'name': None}`.
- `_probe_device_node_ids()` → `_probe_device_identities()`, calls
  `probe_device_identity(path)`, pushes
  `('device_identity', path, identity.node_id, identity.name)`.
- New `_handle_result` branch replaces the old `'device_node_id'` one:
  ```python
  if result[0] == 'device_identity':
      path, node_id, name = result[1], result[2], result[3]
      for device in self.devices:
          if device['path'] == path:
              device['node_id'], device['name'] = node_id, name
              break
      if node_id:
          self._dedupe_devices_by_node_id(keep_path=path)
      self._refresh_device_spinner_labels()
      return
  ```
- The `'connected'` handling block (already storing `node_id` on
  `self._active_device_path`'s device entry) also stores `name` -
  already available for free as `result[3]` on the existing `'connected'`
  result tuple (the same `node_name` `_init_meshtastic()` already sends
  for the connection-status label), no new lookup needed. Then runs the
  same dedup call, with `keep_path=self._active_device_path`.
- New `_dedupe_devices_by_node_id(keep_path)`: removes any *other*
  device in `self.devices` sharing `keep_path`'s device's node ID.
  `keep_path` is always the side that just got authoritative
  information (a probe result, or a live connection) - the rule is
  "the side that was just resolved wins," **except** the currently
  active/connected device (`self._active_device_path`) is never removed
  even if it resolved second - dropping the entry the user is actually
  connected to would be actively wrong, not just imprecise.
  ```python
  def _dedupe_devices_by_node_id(self, keep_path):
      keeper = next((d for d in self.devices if d['path'] == keep_path), None)
      if keeper is None or not keeper['node_id']:
          return
      self.devices = [
          d for d in self.devices
          if d['path'] == keep_path
          or d['node_id'] != keeper['node_id']
          or d['path'] == self._active_device_path
      ]
  ```
- `_device_path_from_display()` / `_refresh_device_spinner_labels()`
  pass `device['name']` through to `format_device_display()` too.

### Critical Files

| File | Change |
|------|--------|
| `core/meshtastic_utils.py` | Add `ProbedDevice`, replace `probe_device_node_id()` with `probe_device_identity()`, extend `format_device_display()` with `name` |
| `btcmesh_client_gui.py` | `self.devices` gains `name`; probe/result handling renamed and extended; new `_dedupe_devices_by_node_id()`; `'connected'` handling stores name too |
| `tests/test_meshtastic_utils.py` | Tests for `probe_device_identity()` (success with name, success without a set name, failure) and `format_device_display()`'s new `name` branch |
| `tests/test_btcmesh_client_gui.py` | Tests for dedup (later-resolved duplicate dropped, active device never dropped even if resolved second), name flowing through from both probe and live-connection paths |
| `project/issues.txt` | Update Issue 37 once implemented - this fixes its duplicate-device half |

### Key Design Decisions

1. **`ProbedDevice` as a null-object, not `Optional[ProbedDevice]`** -
   callers always get a value with two possibly-`None` fields rather
   than needing a None-check before destructuring; matches this
   project's stated preference for dataclasses over ad-hoc `None`/tuple
   returns.
2. **Rename rather than keep both functions** - `probe_device_node_id()`
   has no callers outside this same epic's still-open, unmerged PRs, so
   there's no compatibility reason to keep it alongside a new function;
   a clean rename avoids two near-duplicate probe paths.
3. **Dedup is a display-layer fix, not a probe-cost fix** - explicitly
   not solving the "every candidate still gets a full probe" cost (see
   Context above); that's a separate, complementary fix already
   proposed in Issue 37 (serial-number-based pre-filtering before the
   probe stage even starts).
4. **Active device is dedup-exempt** - the one edge case where "newest
   resolution wins" would be actively wrong, not just a coin-flip
   between two equally-valid choices.

### Verification

- **Unit tests**: `probe_device_identity()` returns a name alongside the
  node ID on success, `ProbedDevice(None, None)` on failure (never
  raises, never returns bare `None`); `format_device_display()`'s three
  branches (name+id, id-only, neither); dedup removes the later-resolved
  duplicate but never the active device; name flows through from both
  the probe path and the live-connection path.
- **Regression check**: full suite still passes.
- **Manual**: re-run the same real-hardware scenario that surfaced
  Issue 37 (Heltec + Seeed + Story 26.7 relay board attached) - confirm
  the dropdown settles to 3 entries, not 5 (2 real devices with names,
  relay board's 2 false-positive ports still present and still
  unlabeled - dedup doesn't touch those), and that the Heltec shows its
  configured name, not a bare path.
