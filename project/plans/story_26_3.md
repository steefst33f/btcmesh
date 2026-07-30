# Story 26.3 Implementation Plan: Stable Device Identity in Device Scanning

## Context

**Why this change:**
EPIC 5's `DeviceWatchdog` (Story 26.4, not yet built) needs to recognize a
Meshtastic device after a power-cycle recovery, even if its OS-assigned
serial path changes on re-enumeration (already observed this session: a
device came back under a completely different path after a reset). The
epic plan's own Key Design Decision #2 says to "match by stable serial
number, not device path" — `core/meshtastic_utils.py::scan_meshtastic_devices()`
currently only returns `List[str]` of paths, with no other identifying
info available.

**Real-world caveat found while grounding this plan:** checked
`serial.tools.list_ports.comports()`'s actual `serial_number` field
against every device currently on hand, and reliability is highly
**chip-dependent**:
- Two CP2102-based boards both reported the exact same `serial_number`
  (`"0001"`) — a common factory-default value on cheap CP2102 modules,
  **not unique** if an operator has more than one such board.
- A CH340-based board reported `serial_number = None` entirely — CH340 is
  well known for not exposing a real USB serial number at all.
- Only a native-USB ESP32-S3 board reported a genuinely unique,
  MAC-derived serial number.

So `serial_number` is a **best-effort** identifier, not a guaranteed-unique
one — this story exposes it for `DeviceWatchdog` to use when available,
but Story 26.4 will need a documented fallback (e.g. treating "the one
port that disappeared and reappeared" as a heuristic, or falling back to
path-based matching) for boards where it's `None` or non-unique. Flagging
this now so it isn't a surprise later.

**Goal/Outcome:** expose `serial_number`/`description` alongside each
device's path, **without changing the existing `scan_meshtastic_devices()`
return type** — both GUIs (`btcmesh_client_gui.py`, `btcmesh_server_gui.py`)
use its `List[str]` result directly for Kivy `Spinner.values`, display
text, and as the port string passed straight into `connect()`. Changing
the return type would ripple into both GUIs' spinner logic mid-epic for a
feature only `DeviceWatchdog` actually needs. Instead, add a new, separate
function and leave the existing one and both GUIs untouched.

---

## Implementation

### `core/meshtastic_utils.py`

Add a `DeviceInfo` dataclass and a new `scan_meshtastic_devices_detailed()`
function, reusing the exact same filter + `eliminate_duplicate_port`
dedup logic as the existing function (that function dedups a list of path
strings, so detailed results are produced by first deduping their paths,
then keeping only the `DeviceInfo` entries whose path survived):

```python
from dataclasses import dataclass

@dataclass
class DeviceInfo:
    path: str
    serial_number: Optional[str]
    description: Optional[str]


def scan_meshtastic_devices_detailed() -> List[DeviceInfo]:
    """Like scan_meshtastic_devices(), but also returns each device's
    serial_number/description for stable-identity matching (Story 26.4).

    serial_number is best-effort, not guaranteed-unique or even present -
    reliability is chip-dependent (e.g. confirmed empirically: CH340-based
    boards report None; some CP2102 boards share an identical factory-
    default value across multiple physical devices). Callers must not
    assume it uniquely identifies a device on its own.
    """
    try:
        from meshtastic.util import blacklistVids, eliminate_duplicate_port
        import serial.tools.list_ports

        candidates = [
            port
            for port in serial.tools.list_ports.comports()
            if port.vid is not None and port.vid not in blacklistVids
        ]
        candidates.sort(key=lambda p: p.device)

        surviving_paths = set(
            eliminate_duplicate_port([p.device for p in candidates])
        )
        return [
            DeviceInfo(
                path=p.device,
                serial_number=p.serial_number,
                description=p.description,
            )
            for p in candidates
            if p.device in surviving_paths
        ]
    except ImportError:
        return []
    except Exception:
        return []
```

`scan_meshtastic_devices()` itself is untouched — kept exactly as-is for
both GUIs.

---

## Critical Files

| File | Change |
|------|--------|
| `core/meshtastic_utils.py` | Add `DeviceInfo` dataclass + `scan_meshtastic_devices_detailed()` |
| `tests/test_meshtastic_utils.py` | New tests for the detailed scan function |
| `project/plans/story_26_1.md` | Note Story 26.3 done, link the serial_number reliability caveat for 26.4 |

No changes to `btcmesh_client_gui.py`, `btcmesh_server_gui.py`, or the
existing `scan_meshtastic_devices()` — this is purely additive.

---

## Key Design Decisions

1. **New function, not a changed return type** — avoids an unreviewed
   ripple through both GUIs' spinner/connect logic mid-epic, per the
   epic plan's own suggested alternative. `DeviceWatchdog` (26.4) is the
   only planned consumer of the detailed info.
2. **`serial_number` is documented as best-effort, not authoritative** —
   grounded in real data gathered this session (chip-dependent
   reliability, occasionally `None`, occasionally a shared factory
   default across multiple boards). This is called out explicitly in
   the docstring and the epic plan so Story 26.4 designs a fallback
   rather than assuming it always works.
3. **Reuses `eliminate_duplicate_port` rather than reimplementing
   dedup logic** — that function only operates on plain path strings, so
   detailed results are produced by deduping paths first, then filtering
   the richer objects down to the survivors, keeping a single source of
   truth for the dedup heuristic.

---

## Verification

- **Unit tests** (mocked `serial.tools.list_ports.comports()`, no
  hardware needed): returns `DeviceInfo` entries with correct
  path/serial_number/description; VID blacklist filtering still applies;
  duplicate-port elimination still applies (reuse the same scenarios
  `tests/test_meshtastic_utils.py` already covers for the existing
  function, adapted for the richer return type); `ImportError`/generic
  exception both return `[]`.
- **Regression check**: full suite still passes; existing
  `scan_meshtastic_devices()` tests unchanged since that function itself
  isn't touched.
