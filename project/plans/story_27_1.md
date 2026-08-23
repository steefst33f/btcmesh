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
- New `_dedupe_devices_by_node_id(keep_path)`: removes the duplicate
  device sharing `keep_path`'s node ID. Normally `keep_path` (the side
  that just got authoritative information - a probe result, or a live
  connection) wins and the other entry is dropped, **except** the
  currently active/connected device (`self._active_device_path`) is
  never dropped: if the active device turns out to be the duplicate (it
  resolved first, `keep_path` resolved to the same node ID second),
  `keep_path` is the one dropped instead. (An earlier draft of this rule
  kept *both* sides whenever the active device was involved, since it
  protected `keep_path` unconditionally *and* the active device
  unconditionally - caught before implementation: those two protections
  must be mutually exclusive, not both-or-nothing, or duplicates
  involving the active device never actually collapse.)
  ```python
  def _dedupe_devices_by_node_id(self, keep_path):
      keeper = next((d for d in self.devices if d['path'] == keep_path), None)
      if keeper is None or not keeper['node_id']:
          return
      duplicates = [
          d for d in self.devices
          if d['path'] != keep_path and d['node_id'] == keeper['node_id']
      ]
      if not duplicates:
          return
      if any(d['path'] == self._active_device_path for d in duplicates):
          self.devices = [d for d in self.devices if d['path'] != keep_path]
      else:
          dup_paths = {d['path'] for d in duplicates}
          self.devices = [d for d in self.devices if d['path'] not in dup_paths]
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

---

## Architecture Revision (2026-08-23): Connect-Only-At-Action Model

**Context**: discussing Story 27.3 (server GUI) raised the question of
*why* the client and server GUIs handle device selection so
differently - client auto-connects the moment a device is chosen,
server only connects when "Start Server" is pressed. Tracing it down:
the honest reason isn't "client's job is connect, server's job is
configure" (that's a description, not a cause) - it's that two
specific *features* happen to depend on the client holding a
persistent connection while otherwise idle:

1. The known-nodes destination dropdown (`_update_known_nodes()`,
   Story 11.2) reads `self.iface.nodes`, which needs a live connection.
2. The idle-time device watchdog (Story 28.4) periodically pings an
   already-open connection to catch a wedge before Send.

Neither the server GUI nor either CLI (`btcmesh_client_cli.py`,
`btcmesh_server_cli.py` - both checked directly) has anything like
this: both CLIs resolve a port and connect *only* at the moment they're
about to actually do their one job, then disconnect in a `finally`
block. There's no interactive multi-device selection step in CLI-land
at all - the port is already decided (via `-p`/`.env`) before the
process starts, so this isn't really evidence either way on its own,
but it does confirm "connect only when about to act" is a
well-established, working pattern elsewhere in this codebase already.

**Decision**: adopt one rule for both GUIs - **connect for real only at
the moment of actually acting (Send for the client, Start for the
server)**. Everything before that (browsing the device list, seeing
names/IDs) uses the same brief connect-probe-disconnect cycle
`probe_device_identity()` already provides. This is a bigger change
than "finish Story 27.3" - it revises the client GUI behavior Story
27.2 already implemented, and removes Story 28.4's client-side idle
watchdog. Confirmed acceptable (2026-08-23): none of this code has
real users yet, so there's no backward-compatibility cost to getting
the underlying model right instead of layering Story 27.3 onto an
inconsistency.

**Why the idle watchdog specifically has to go, not just get
disconnected from this change**: its entire premise is "the connection
is already open, periodically verify it's still responsive." With no
ambient connection to ping, the only way to preserve *some* form of
idle liveness-checking would be to periodically reconnect just to test
it - which is the exact rapid-reconnect-cycling pattern this project
has already caught **causing** real wedges (Issue 12, and the Seeed
wedge personally reproduced during this session's Story 27.2
verification work). So idle liveness-checking would work against
itself under this model, not just become redundant. A wedge is instead
discovered at Send time, already handled cleanly by the existing
connect retry (`CONNECT_MAX_ATTEMPTS`) and bounded send timeout (Story
28.1) - a clear, immediate, actionable error instead of a background
maybe-warning that periodically risks provoking the exact problem it's
watching for.

**What happens to the known-nodes dropdown**: it keeps working, just
stops depending on an ambient connection. Its existing manual "Scan"
button (`on_refresh_nodes`) becomes a self-contained brief-connect,
fetch-known-nodes, disconnect action - the same primitive as device
identity probing, applied to a different payload (`get_known_nodes()`
instead of `get_own_node_name()`), off a transport that's opened and
closed within that one action instead of borrowed from an ambient
`self.iface`.

### Shared device-selection module (`gui/gui_common.py`)

The mechanics (probe orchestration, dedup-by-node-ID, reverse-lookup,
relabeling) are identical between the client and server GUIs - this
was already true before this revision (Story 27.3's original plan
above duplicates Story 27.2's methods near-verbatim), and stays true
after it. Per this project's "no duplicated logic" principle, and
since these functions touch Kivy widgets directly (so `core/`, which
must stay UI-free, isn't the right home), they move into
`gui/gui_common.py` - where `StatusLog`/`ConnectionState`/the shared
factory functions already live for cross-GUI concerns - as plain
functions operating on passed-in state rather than bound methods, so
neither GUI file needs to inherit from anything or share instance
state:

```python
def probe_devices_in_background(devices: list, result_queue, skip_paths: frozenset = frozenset()) -> None:
    """Starts a daemon thread that probes each device in `devices` (list
    of {'path', 'node_id', 'name'} dicts) via probe_device_identity(),
    pushing ('device_identity', path, node_id, name) onto result_queue
    for each one not in skip_paths. skip_paths exists for callers that
    still want to exclude specific paths (e.g. one already known some
    other way) - neither GUI uses it after this revision (see below),
    but the hook costs nothing to keep."""

def dedupe_devices_by_node_id(devices: list, keep_path: str, protect_path: str = None) -> tuple[list, dict | None]:
    """Returns (new_devices_list, removed_device_or_None). If keep_path's
    device shares its node ID with another entry, that entry is dropped
    and keep_path's wins - unless the duplicate's path equals
    protect_path, in which case keep_path is dropped instead. Passing
    protect_path=None (the server GUI's case - no live connection ever
    exists during scanning, see below) simply disables that exemption,
    since no device path ever equals None."""

def device_path_from_display(devices: list, text: str) -> str:
    """Reverse lookup: formatted display text -> underlying path, or
    text unchanged as a fallback (sentinel values, already-resolved
    real paths that aren't in `devices`)."""

def refresh_device_spinner_labels(spinner, devices: list, selection_handler=None) -> None:
    """Rebuilds spinner.values from devices, preserving the current
    selection across the relabel. Unbinds/rebinds selection_handler
    around the mutation if given (the client still needs this, even
    without an active-device concept - see below); omitted entirely for
    the server GUI, which has no bound handler to protect."""
```

**Does the client still need dedup's `protect_path` exemption without
an ambient connection?** No live-connection case remains, but a
different, narrower one does: if the user manually selects a
not-yet-fully-probed alias *before* its duplicate resolves, a later
dedup pass could drop the very entry they just selected out from under
them. Accepted as a known edge case rather than engineered around:
worst case the spinner keeps showing that alias's raw, unformatted (but
still perfectly valid) path instead of the pretty label, and Send-time
connection to it still works correctly - `device_path_from_display()`'s
existing fallback rule (return unmatched text as-is) means a stale-but-
real path continues to resolve to a real device either way. Not
reachable in this codebase's actual flow today (mirrors the exact
"probe/selection race" edge case Story 27.2's original design already
accepted for the same reason), so `protect_path` isn't used by the
client under this revision either - both GUIs now call
`dedupe_devices_by_node_id(devices, keep_path)` identically, and the
parameter exists in the shared function's signature only because a
future caller with a genuine live-connection-during-scan scenario might
need it, not because either GUI here does.

**Still needs unbind/rebind in `refresh_device_spinner_labels()` for
the client, even now**: relabeling changes `spinner.text`, and Kivy
Spinner fires its bound `text` handler on any value change - without
unbinding first, a relabel-only mutation would still spuriously
re-trigger the client's selection handler. The server GUI has no
bound handler at all (per the original Story 27.3 plan above), so it
passes `selection_handler=None` and the function skips that step
entirely.

### `btcmesh_client_gui.py` changes

- **Remove**: auto-connect on `devices_found` (single-device case),
  `on_device_selected`'s immediate `_disconnect_device()` +
  `_init_meshtastic()`, the Story 28.4 watchdog thread/wiring
  (`_start_watchdog_thread`, `build_device_watchdog` import and use,
  `watchdog`/`power_control` state), `_active_device_path` (no longer
  meaningful with no ambient connection).
- **Keep, unchanged**: the scan itself, `self.devices` state shape,
  `_probe_device_identities()`'s call site (now unconditional -
  always probe, matching the server GUI, since there's no more
  "about to auto-connect anyway" shortcut for the single-device case
  either).
- **Move**: real connection logic (what `_init_meshtastic()` already
  does) into `on_send_pressed()`, resolving the device path via
  `device_path_from_display(self.devices, self.device_spinner.text)`
  first - mirrors `btcmesh_client_cli.py`'s `run_send()` almost
  exactly (connect, send, disconnect in a `finally`), just wrapped in
  the existing background-thread + `result_queue` pattern this file
  already uses throughout.
- **Change**: `_update_known_nodes()` (Story 11.2, triggered by
  `on_refresh_nodes`) opens its own transport, calls
  `get_known_nodes()`/`get_own_node_name()` off it, and disconnects -
  no longer reads an ambient `self.iface`.

### `btcmesh_server_gui.py` changes

Story 27.3's original plan above still applies almost entirely - it
already matches the connect-only-at-Start model. The only change from
that plan: `_probe_device_identities()`, `dedupe_devices_by_node_id()`,
`device_path_from_display()`, `refresh_device_spinner_labels()` are now
imported from `gui/gui_common.py` rather than reimplemented locally,
and the fix to `_on_save_settings()`/`on_start_pressed()` (resolving
`self.device_spinner.text` through `device_path_from_display()` before
using it as a literal path) stands exactly as planned.

### Critical Files (supersedes the table in Story 27.3's section above)

| File | Change |
|------|--------|
| `gui/gui_common.py` | New: `probe_devices_in_background()`, `dedupe_devices_by_node_id()`, `device_path_from_display()`, `refresh_device_spinner_labels()` |
| `btcmesh_client_gui.py` | Remove auto-connect-on-select and Story 28.4 watchdog wiring; move real connection into `on_send_pressed()`; `_update_known_nodes()` opens its own brief connection instead of reading `self.iface` |
| `btcmesh_server_gui.py` | Adopt the shared `gui/gui_common.py` functions; fix `_on_save_settings()`/`on_start_pressed()` to resolve display text to a real path first |
| `tests/test_gui_common.py` | New tests for the four extracted functions |
| `tests/test_btcmesh_client_gui.py` | Remove tests for deleted auto-connect/watchdog behavior; add tests for connect-at-Send and the new known-nodes fetch path |
| `tests/test_btcmesh_server_gui.py` | Tests mirroring the client's for the shared-function usage; `_on_save_settings()`/`on_start_pressed()` path-resolution tests |
| `project/tasks.txt` | Story 28.4 marked superseded by this revision; Story 27.2/27.3 notes updated |
| `project/issues.txt` | Issue 37 updated once server GUI also gets the fix |

### Verification

- **Unit tests**: the four shared functions tested directly in
  `tests/test_gui_common.py`, independent of either GUI; both GUI test
  files updated for the new connection-lifecycle and known-nodes
  behavior; full suite green.
- **Manual**: client GUI - selecting a device no longer opens a
  connection (confirm via log: no "Connecting to..." until Send is
  pressed); Send still works end-to-end; known-nodes "Scan" still
  populates the destination dropdown. Server GUI - same real-hardware
  multi-device scenario as before, plus confirming Start Server
  connects to the correct physical device when a labeled entry is
  selected, and no device-related log/behavior regression from
  removing the client's Story 28.4 watchdog (server keeps its own
  watchdog, wired at Start, unchanged).

---

## Client GUI Implementation Notes (2026-08-23)

Written up after implementing (see commit "Client GUI: connect only at
Send, adopt shared device-selection module") - the "Architecture
Revision" section above stated intent at the bullet-point level; this
records what was actually built, since a change this size deserves a
real record, not just the diff.

### `_connect_with_retry(self, port)` replaces `_init_meshtastic()`

The old `_init_meshtastic()` ran as its own background thread and
communicated outcomes (`'connected'`, `'connection_failed'`,
`'connection_error'`, `'connection_initializing'`, `'transport_ready'`)
purely through `result_queue`, because it was fired from
`on_device_selected`/`devices_found` - code running on Kivy's main
thread, which can't block. With connecting now happening *inside* the
already-background send thread, that indirection is unnecessary: a
plain synchronous method can block, retry, and either return a
connected transport or raise.

```python
def _connect_with_retry(self, port):
    """Blocking connect-with-retry, called only from the send thread."""
    self.result_queue.put(('log', f"Connecting to Meshtastic device{f' ({port})' if port else ''}...", logging.INFO))
    last_error = None
    for attempt in range(CONNECT_MAX_ATTEMPTS):
        try:
            transport = MeshtasticSerialTransport()
            transport.connect(port)
            if not transport.local_node_id:
                transport.disconnect()
                raise TransportConnectionError("Could not retrieve device info. Ensure device is connected.")
            return transport
        except TransportConnectionError as e:
            last_error = e
            is_transient = any(x in str(e).lower() for x in ['resource temporarily unavailable', 'busy'])
            if is_transient and attempt < CONNECT_MAX_ATTEMPTS - 1:
                self.result_queue.put(('log', "Device is initializing, please wait...", logging.WARNING))
                time.sleep(CONNECT_RETRY_DELAY_SECONDS)
                continue
            break
    # ... map last_error to a friendlier message, then raise TransportConnectionError
```

Same retry count/delay and the same transient-vs-permanent distinction
as the old code; only the *shape* changed (return/raise instead of
result_queue push-and-return-True/False).

### `_send_transaction_thread(self, dest, tx_hex, dry_run, port)` - the new center of gravity

```python
def _send_transaction_thread(self, dest, tx_hex, dry_run, port):
    if dry_run:
        self._run_preview(tx_hex)
        return
    try:
        transport = self._connect_with_retry(port)
    except TransportConnectionError as e:
        self.result_queue.put(('error', str(e)))
        return

    self.transport = transport
    self.iface = transport._iface
    try:
        node_id = transport.local_node_id
        node_name = get_own_node_name(self.iface)
        self.result_queue.put(('connected', self.iface, node_id, node_name))

        if dest.lower() == node_id.lower():
            self.result_queue.put(('error', "Cannot send to your own node"))
            return

        sender = TransactionSender(self.transport)
        self._active_sender = sender
        # ... on_chunk_sending/on_progress/on_response_received callbacks, unchanged
        result = sender.send_transaction(tx_hex, dest, ...)
        self.result_queue.put(('send_result', result))
    except Exception as e:
        self.result_queue.put(('error', str(e)))
    finally:
        self._active_sender = None
        self.transport.disconnect()
        self.transport = None
        self.iface = None
        self.result_queue.put(('disconnected',))
```

Key points:
- The self-send check (`dest == own node ID`) moved here from
  `validate_send_inputs()`, since the own node ID genuinely isn't
  knowable before connecting now - it's discovered, not pre-validated.
  It still fires as a plain `'error'` result, so it reuses
  `process_result()`'s existing stop-sending/re-enable-controls path
  with no changes there.
- The `finally` block is the only place that disconnects - covers the
  happy path, the self-send rejection, and any exception from
  `sender.send_transaction()` uniformly. A new `'disconnected'` result
  type resets `connection_label` back to "Not connected" once it runs.
- `on_send_pressed()` resolves `port = device_path_from_display(self.devices, self.device_spinner.text)`
  on the *main* thread (where the spinner's current selection is safe
  to read) and passes it as a plain argument into the thread, rather
  than having the thread re-read `self.device_spinner.text` itself.

### `validate_send_inputs(dest, tx_hex)` - signature shrunk from 5 params to 2

Dropped `has_iface`, `dry_run`, `own_node_id` entirely. The function is
now pure format validation (destination shape, tx_hex shape) with no
opinion on connection state at all - `has_iface` no longer makes sense
to check ahead of time (there's nothing to check - connecting hasn't
happened yet), and `own_node_id` isn't known yet either (see above).

### `on_refresh_nodes()` / `_update_known_nodes(nodes)` - split into fetch + apply

`_update_known_nodes()` used to read `self.iface` directly and do both
the fetching and the UI update in one method. Split in two:
`on_refresh_nodes()` now does its own brief connect → `get_known_nodes()`
→ disconnect (mirroring `_connect_with_retry`'s shape, but without the
retry loop - a failed fetch just logs an error, it doesn't need the
same robustness as the actual send path), pushing
`('known_nodes_fetched', nodes)`; `_update_known_nodes(nodes)` is now
the pure UI-update half, taking the already-fetched list as a
parameter instead of reaching for `self.iface`.

### `_handle_result()` - net changes

- `devices_found`: single-device case no longer calls `_init_meshtastic()`;
  both branches now unconditionally call the shared
  `probe_devices_in_background()`.
- `device_identity`: now calls the shared `dedupe_devices_by_node_id()`/
  `refresh_device_spinner_labels()` instead of bound-method equivalents.
- Removed entirely: `transport_ready`, `watchdog_attempt`,
  `watchdog_recovered`, `watchdog_failed` branches, and the block that
  updated `self.devices` from a live `'connected'` result (probing
  already covers identity now - see the "always probe" point above).
- Added: `known_nodes_fetched` (calls `_update_known_nodes(result[1])`),
  `disconnected` (resets `connection_label`).

### Dead code removed alongside the above

`process_result()`'s `connection_failed`/`connection_error`/
`connection_initializing` branches - nothing produces those result
types anymore, since `_connect_with_retry()` only ever returns a
transport or raises. Removed rather than left in place, since keeping
a pure function's branches for inputs nothing ever sends again is
exactly the kind of unused code this project's coding principles call
out. The `STATE_CONNECTION_FAILED`/`STATE_CONNECTION_ERROR`
`ConnectionState` constants went with them (only ever used to build
those three branches' `connection_text`).

### Critical Files (this implementation)

| File | Change |
|------|--------|
| `btcmesh_client_gui.py` | `_connect_with_retry()` replaces `_init_meshtastic()`; `_send_transaction_thread()` does connect+send+disconnect; `validate_send_inputs()` shrunk to 2 params; `on_refresh_nodes()`/`_update_known_nodes()` split into fetch+apply; `_handle_result()` updated per above; dead `process_result()` branches and `STATE_CONNECTION_FAILED`/`STATE_CONNECTION_ERROR` removed |
| `tests/test_btcmesh_client_gui.py` | `TestSendButtonValidationStory91` rewritten for the 2-param signature; `TestDeviceConnectionRetryAndSelectionFix` rewritten around `_connect_with_retry()`; `TestNodeIdDisplayStory272` rewritten to test this file's wiring only (dedup/lookup/relabel logic itself is covered in `tests/test_gui_common.py`); new `TestConnectAndSendFlow` (5 tests: dry-run skips connecting, full happy path, connect failure, self-send rejection, disconnect-on-exception) and `TestKnownNodesFetchFlow` (4 tests); `TestDeviceWatchdogStory284` deleted entirely |

### Verification (this implementation)

- **Unit tests**: full suite 792/792 passing after this change (from
  780 before Story 27.x began).
- **Manual**: not yet done as of this write-up - still needed before
  trusting the connect-at-Send timing and the self-send check against
  real hardware (see the parent "Architecture Revision" section's
  Verification for what to check).

---

## Fix: Known-Nodes Staleness on Device Selection (2026-08-23)

**Found during real-hardware verification** of the Architecture
Revision above: known nodes are per-device (each physical Meshtastic
device has its own NodeDB of nodes it's heard from), but nothing
re-fetches them when the *device selection* changes - only Send
connects now, which is too late for populating the destination picker
while the user is still composing the transaction. Result: switching
devices left the destination dropdown either empty or showing the
*previous* device's known nodes, silently wrong (a node reachable from
device A isn't necessarily reachable from device B).

**Fix**: bring back a bound `on_device_selected` handler - but scoped
narrowly. Its only job is a single brief connect that fetches *both*
the newly-selected device's identity (node_id/name, for
labeling/dedup) and its known nodes (for the destination dropdown) in
one connection, then disconnects. It does **not** hold a persistent
connection - Send still does its own separate connect, unchanged.

```python
def on_device_selected(self, spinner, text):
    if text in (NO_DEVICES_TEXT, SCANNING_TEXT, SELECT_DEVICE_TEXT, ''):
        return
    path = device_path_from_display(self.devices, text)
    self.status_log.add_message("Fetching device info and known nodes...")

    def fetch_thread():
        try:
            transport = MeshtasticSerialTransport()
            transport.connect(path)
        except TransportConnectionError as e:
            self.result_queue.put(('log', f"Could not fetch device info: {e}", logging.ERROR))
            return
        try:
            node_id = transport.local_node_id
            name = get_own_node_name(transport._iface)
            self.result_queue.put(('device_identity', path, node_id, name))
            nodes = get_known_nodes(transport._iface)
            self.result_queue.put(('known_nodes_fetched', nodes))
        finally:
            transport.disconnect()

    threading.Thread(target=fetch_thread, daemon=True).start()
```

Reuses the *existing* `device_identity` and `known_nodes_fetched`
result handling in `_handle_result()` unchanged - this just adds a new
place that pushes those same result types.

**Why fetch identity here too, not just known nodes**: doing both in
one connection avoids a real collision. The single-device auto-select
case sets `device_spinner.text = devices[0]` immediately, which now
fires `on_device_selected` - if that only fetched known nodes while a
*separate* background probe (`probe_devices_in_background`) also tried
to connect to the same sole device for identity, both would race for
the same serial port. Folding identity into this same connection
avoids the race entirely for that case, rather than adding
synchronization to prevent it.

**Consequence for `devices_found`'s single-device branch**: stop
calling `probe_devices_in_background()` there (revert to the original
Story 27.2 skip-probe-for-single-device behavior) - identity now
arrives for free from `on_device_selected`'s fetch instead, the same
role the live Send connection played before this revision. The
multi-device branch is unaffected: it still probes every candidate in
the background for labeling, and still races on-select the same
already-accepted way Story 27.2 documented ("probe/selection race...
no lock/cancellation added") - not a new tradeoff, just extended to
now include the known-nodes fetch too.

**`refresh_device_spinner_labels()` call sites**: now pass
`selection_handler=self.on_device_selected` again (was `None`),
restoring the unbind/rebind protection - otherwise a label-only
update (e.g. a background probe resolving a *different* device's
name) would spuriously re-fire `on_device_selected` and refetch known
nodes for no reason.

Files touched: `btcmesh_client_gui.py` (`on_device_selected()` added
back, bound in `_build_ui()`; `devices_found`'s single-device branch;
`refresh_device_spinner_labels()` call site), `tests/test_btcmesh_client_gui.py`.

### Follow-up refinements (found immediately after, same real-hardware session)

1. **Clear known nodes immediately on selection, don't wait for the
   fetch.** The fix above still leaves the *previous* device's known
   nodes visible for the few seconds the new fetch takes - not
   indefinitely stale anymore, but still momentarily wrong. Fix:
   `on_device_selected()` calls `self._update_known_nodes([])`
   synchronously, right after the sentinel-text guard and before
   kicking off the background fetch thread - reuses the existing pure
   UI-update function rather than duplicating its placeholder logic.
   The real list then overwrites this placeholder once
   `known_nodes_fetched` arrives, same as today.

2. **Error message says "connection" when the user never asked to
   connect.** Selecting a non-Meshtastic candidate (e.g. a false-
   positive from Issue 37, like the relay board's own port) surfaces
   the raw `TransportConnectionError` text verbatim - e.g. "Timed out
   waiting for connection completion" - which reads like a failed Send
   attempt, not a background info fetch the user didn't explicitly ask
   for. `_connect_with_retry()` already translates raw errors into
   friendlier text (`"No Meshtastic device found"`, permission-denied,
   port-open failures) but that mapping was never shared - both
   `on_device_selected()` and `on_refresh_nodes()` log the raw
   exception text unmodified. Fix: extract the mapping into a plain
   module-level function, add a case for the timeout wording
   specifically (framed as "didn't respond" rather than "connection
   failed"), and reuse it in all three places:
   ```python
   def _friendly_connect_error(port: str, exc: TransportConnectionError) -> str:
       msg = str(exc)
       if "No Meshtastic" in msg or "No serial" in msg:
           return "No Meshtastic device found"
       if "Permission denied" in msg:
           return f"Permission denied accessing {port or 'device'}"
       if "could not open port" in msg.lower():
           return f"Could not open port {port or '(auto-detect)'}"
       if "timed out" in msg.lower() or "timeout" in msg.lower():
           return f"{port or 'Device'} did not respond - it may not be a Meshtastic device, or isn't responding right now"
       return msg
   ```
   The surrounding log prefix each call site already uses ("Could not
   fetch device info: ...", "Could not fetch known nodes: ...", "Failed
   to connect: ...") keeps framing *what* was being attempted; this
   only fixes *why* it failed reading like an unrelated Send attempt.

**Status: implemented and real-hardware verified (2026-08-23).** Test
coverage added in `tests/test_btcmesh_client_gui.py`
(`TestDeviceSelectedFetchFlow.test_clears_known_nodes_immediately_before_fetch_completes`,
`TestFriendlyConnectError`) - full suite (85 client-GUI tests, 803
project-wide) green. Verified live with the Seeed/Heltec/relay-board
setup: switching devices blanks the known-nodes list immediately
instead of showing the previous device's stale entries; selecting a
non-Meshtastic port now reads "...did not respond - it may not be a
Meshtastic device..." instead of "Waiting for connection completion".
User confirmed both work as intended; also flagged a (pre-existing,
never-had-one) missing loading/busy indicator during these background
probes as a nice-to-have for later - logged as Issue 39, not fixed
here.

### Full end-to-end mesh verification (2026-08-23)

With both GUIs live (client on Heltec `!7c5b4418`, server on Seeed
`!aee5ab3c`), ran a full 15-chunk send start to finish under the
connect-only-at-Send model. First attempt (session `4dcfb`) hit
asymmetric RF loss on chunk 9's ACK reply - client exhausted its retry
budget and disconnected before the server's own (slower) reassembly
timeout fired and NACKed; see Issue 40 for the full analysis (confirms
Issue 23.3's NACK-on-timeout mechanism worked correctly - the gap is
just that the client isn't listening anymore by the time it arrives).
Second attempt (session `318db`) completed cleanly: all 15 chunks
ACKed on first transmission, server confirmed `ALL_CHUNKS_RECEIVED`.
Broadcast itself NACKed with `Bitcoin RPC not connected` - expected,
no Bitcoin Core node was running in this environment; out of scope for
this verification, not investigated further.

**This confirms the connect-only-at-Send architecture revision works
end-to-end on real hardware** - device selection, brief identity/
known-nodes probes, and the full connect→send-all-chunks→disconnect
flow all behave correctly for a complete transaction, not just the
individual pieces tested earlier in this session.

## Story 27.3 Implementation Notes (server GUI) - Final

Implemented on branch `story-27-3` (stacked on `story-27-2`), following
the design already specified in this doc's "Architecture Revision"
section's `btcmesh_server_gui.py` changes subsection above - the server
GUI now imports `probe_devices_in_background()`,
`dedupe_devices_by_node_id()`, `device_path_from_display()`,
`refresh_device_spinner_labels()` from `gui/gui_common.py` rather than
reimplementing them, matching the client GUI. Concretely:

- New `self.devices` state, rebuilt on every scan.
- `devices_found` handling builds `self.devices`, formats spinner
  labels via `format_device_display()`, and **always** probes every
  found device (including the single-device case) - the server never
  auto-connects on selection, so this background probe is its only path
  to ever learning identities (difference #3 from the original Story
  27.3 notes still holds, see "why are these differences still true"
  discussion above).
- New `device_identity` result branch mirrors the client's, but with no
  `selection_handler` passed to `refresh_device_spinner_labels()` - the
  server spinner has no bound handler to protect (difference #1).
- Fixed two real, pre-existing bugs: `_on_save_settings()` and
  `on_start_pressed()` both read `self.device_spinner.text` as a
  literal path - broken once labels became `"Name (!nodeid)"`. Both now
  resolve through `device_path_from_display()` first.

### Two issues found via real-hardware testing (both fixed except one deferred)

1. **Auto-detect disappeared from the dropdown after the first scan**
   (fixed here). `refresh_device_spinner_labels()` rebuilt
   `spinner.values` purely from the probed `devices` list, with no way
   to keep a sentinel like `DEVICE_AUTO_DETECT` (which isn't in
   `devices`) in the list - the client GUI has no such sentinel so this
   never surfaced there. Added an `extra_values` parameter (default
   `()`, so the client's call site and behavior are completely
   unchanged) that the server passes `[DEVICE_AUTO_DETECT]` to.
2. **No auto-scan on startup** (fixed here, user-requested parity fix).
   The server dropdown used to start with just "Auto-detect" until Scan
   was clicked manually - inconsistent with the client GUI's 1s-after-
   launch auto-scan, and felt off once both GUIs share the same
   device-selection model. Added the same
   `Clock.schedule_once(lambda dt: self._on_scan_devices(None), 1)`
   call to `__init__`.
3. **Auto-detect + Start Server silently "hangs" with multiple devices
   attached** (found, NOT fixed here - logged as Issue 41). Traced
   through the installed meshtastic library: `SerialInterface(devPath=None)`
   calls `meshtastic.util.our_exit()` (`sys.exit()`) when more than one
   serial candidate exists, raising `SystemExit` - a `BaseException` our
   `transport/meshtastic_serial.py`'s `except Exception` doesn't catch,
   so it silently kills the connecting thread instead of surfacing a
   normal `TransportConnectionError`. Not GUI- or Story-27.3-specific
   (any `connect(None)` caller with multiple devices hits this); deferred
   to its own branch per the one-issue-one-branch convention, matching
   how Issue 38 was handled. Workaround: select an explicit device
   instead of Auto-detect.

### Verification

- **Unit tests**: `TestNodeIdDisplayStory273` (4 tests, mirroring the
  client's `TestNodeIdDisplayStory272` with the "always probe"/"no
  selection_handler" differences), plus regression tests for both
  path-resolution fixes (`_on_save_settings`, `on_start_pressed`) and
  the Auto-detect-persistence fix (`gui/gui_common.py`'s
  `extra_values` param, tested directly in `tests/test_gui_common.py`
  and via a real-call regression test in `tests/test_btcmesh_server_gui.py`).
  Full suite: 812/812 passing.
- **Real hardware**: server GUI restarted with all fixes; confirmed live
  that the dropdown auto-populates ~1s after launch (no manual Scan
  needed), and that Auto-detect stays present in the dropdown after a
  scan/probe cycle completes. User confirmed both work as expected.
  Auto-detect + Start Server (Issue 41) intentionally not retested here
  - explicit-device selection is the only supported path until that's
  fixed.
