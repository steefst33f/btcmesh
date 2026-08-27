# Epic 9 / Story 30.2: Generalize destination validation onto `BaseTransport` — Implementation Plan

## Context

Story 30.1 added `MeshCoreSerialTransport`, whose destinations are hex-encoded
public keys, not Meshtastic's `!hex8` node IDs. `core/protocol.py::validate_destination()`
only ever knew the Meshtastic format, so 30.1 landed a deliberate, narrow
stopgap: `btcmesh_client_cli.py::cli_main()` skipped destination validation
entirely when `--transport meshcore` was selected. That was documented in
`project/tasks.txt` (Story 30.2) and `project/plans/story_30_1.md` as this
story's job: move the validation onto `BaseTransport` per-transport, so each
transport validates its own addressing format, and remove both the CLI
stopgap and the Meshtastic-only free function.

## Approach

Add an abstract `validate_destination(destination: str) -> None` method to
`BaseTransport` (raises `ValueError`, mirrors the existing free function's
contract). Each concrete transport implements its own format check.
Callers stop importing `core.protocol.validate_destination` and instead call
it on whichever transport instance they already hold (or construct one
purely to validate, pre-connect — cheap, since `__init__` never opens a
connection in either transport).

### 1. `transport/base.py`
New abstract method alongside the others:
```python
@abstractmethod
def validate_destination(self, destination: str) -> None:
    """Validate a destination identifier's structural format for this
    transport's addressing scheme.

    Raises:
        ValueError: If destination is empty or malformed for this transport.
    """
    ...
```

### 2. `transport/meshtastic_serial.py`
`core/protocol.py::validate_destination()`'s body moved over verbatim as a
method — same rule (non-empty, starts with `!`), same messages, so this is a
no-behavior-change move for Meshtastic.

### 3. `transport/meshcore_serial.py`
New check for MeshCore's own format: non-empty, valid hex characters, even
length (whole bytes — a public key/prefix can't be a half byte). Reuses
`core.protocol.is_valid_hex`:
```python
def validate_destination(self, destination: str) -> None:
    if not destination:
        raise ValueError("Destination cannot be empty")
    if not is_valid_hex(destination) or len(destination) % 2 != 0:
        raise ValueError("Destination must be a hex-encoded public key or prefix")
```

### 4. `core/protocol.py`
`validate_destination()` deleted entirely — fully superseded.

### 5. `client/sender.py`
`TransactionSender.send_transaction()` calls `self.transport.validate_destination(destination)`
instead of the free function; the now-unused import dropped.

### 6. `btcmesh_client_cli.py`
The `if args.transport == "meshtastic":` stopgap block removed, replaced
with an unconditional call using whichever transport was selected:
```python
try:
    get_transport(args.transport).validate_destination(args.destination)
except ValueError as e:
    print(f"Invalid destination: {e}", file=sys.stderr)
    return 1
```

### 7. `btcmesh_client_gui.py`
The GUI is hardcoded to Meshtastic (Story 30.4 territory, unchanged here).
`validate_send_inputs()` now calls `MeshtasticSerialTransport().validate_destination(dest)`
instead of the removed free function.

### 8. `btcmesh_server_cli.py`
No change — its `transport_name == "meshtastic"` guards are for the Story
26.7 relay-board check and `MESHTASTIC_SERIAL_PORT` env fallback, unrelated
to destination validation.

## Test changes

- `tests/test_transport_base.py`: `validate_destination` added to
  `StubTransport` and to every `Incomplete` test class; new
  `test_missing_validate_destination_raises_type_error` case.
- `tests/test_meshtastic_serial_transport.py`: new test class covering
  `validate_destination` — valid `!hex8`, empty, missing `!` prefix, `None`.
- `tests/test_meshcore_serial_transport.py`: new test class covering
  MeshCore's rule — valid full key, valid prefix, empty, `None`, non-hex,
  odd length.
- `tests/test_protocol.py`: `TestValidateDestination` deleted (function no
  longer exists); import dropped.
- `tests/test_client_sender.py`: the two destination tests that hardcoded
  Meshtastic's rule replaced with two transport-agnostic ones — one
  asserting `send_transaction()` calls `transport.validate_destination(destination)`,
  one driving the error path via `transport.validate_destination.side_effect`.
- `tests/test_btcmesh_client_cli.py`: four tests updated. Three that
  asserted `get_transport` was *not called* for invalid input now assert
  `run_send` was not called instead — `get_transport` is legitimately
  called once now to construct a throwaway instance for validation, even
  when the input is ultimately rejected; that's not a connection attempt
  (`transport.connect()` is never reached), so `run_send`-not-called is the
  accurate proxy. The `--transport meshcore` test that documented the old
  "skips bang-prefix validation" stopgap was renamed/rewritten to show the
  destination is now actually validated (accepted when well-formed hex, via
  `test_meshcore_transport_accepts_its_own_hex_format`); a new
  `test_meshcore_transport_rejects_malformed_destination` proves the
  stopgap is gone by showing a non-hex MeshCore destination is now rejected
  up front.

## `project/tasks.txt`

Story 30.2's checkboxes flipped to `[x]`, "Not yet done" note replaced with
a completion note.

## Verification

- `python -m unittest discover -s tests -p 'test_*.py'` — full suite green.
- `python btcmesh_client_cli.py --transport meshcore -d <bad-hex> -tx <hex> --dry-run`
  now rejects a malformed MeshCore destination (previously silently passed
  through per the stopgap).
- `python btcmesh_client_cli.py -d notanodeid -tx <hex> --dry-run` (default
  Meshtastic transport) — still rejects with the same "must start with '!'"
  message as before — no behavior change for existing Meshtastic users.

---

## Implementation Completion

**Status:** Complete. All checkboxes above implemented exactly as planned;
no deviations from the approach.

**Test results:** Full suite run via the shared venv
(`/Users/Steef/Workspace/btcmesh/.venv`, which has `requests`/`meshtastic`/
`pyserial` installed — `meshcore` itself is not installed there, but its
tests mock `sys.modules['meshcore']` so that's not required): 914 tests, all
passing (up from 906 before this story — net new coverage in
`test_transport_base.py`, `test_meshtastic_serial_transport.py`, and
`test_meshcore_serial_transport.py`, offset by the removal of
`test_protocol.py::TestValidateDestination`'s 4 cases).

**Manual verification:** Not re-run against real hardware for this story —
`validate_destination()` is a pure format check with no I/O, and the CLI's
dry-run/error-path behavior is covered directly by the updated
`tests/test_btcmesh_client_cli.py` suite (including the two new tests that
specifically prove the Story 30.1 stopgap is gone: a malformed MeshCore
destination is now rejected, and a well-formed one is accepted through the
real per-transport check).
