# Epic 9 / Story 30.1: MeshCore Serial Transport — Implementation Plan

## Context

BTCMesh currently only speaks Meshtastic. Prior research (`project/mesh_network_analysis.md`) found **MeshCore** to be the closest live alternative: it runs on the identical hardware class (Heltec, T-Beam, T-Echo, T-Deck, RAK), and has a "companion protocol" over serial/BLE/TCP that is structurally similar to how BTCMesh already talks to Meshtastic devices. `transport/base.py`'s `BaseTransport` abstraction was explicitly designed with a second protocol implementation like this in mind - `client/sender.py` and `server/receiver.py` are already fully transport-agnostic and need zero changes.

**Scope:** wired/USB-serial only. BLE - for either Meshtastic or MeshCore - is out of scope until serial works well end-to-end for both.

**The one real technical wrinkle:** the `meshcore` Python client library (`meshcore_py`) is **asyncio-native** (`await MeshCore.create_serial(...)`, `await meshcore.commands.send_msg(...)`, async event-subscription callbacks), while `BaseTransport` and every existing implementation/caller in this codebase is synchronous. This plan's main job is designing that bridge cleanly, not just writing another `BaseTransport` subclass.

**Outcome:** a `transport/meshcore_serial.py` implementing `BaseTransport`, selectable via a new `--transport` CLI flag, that can send/receive BTCMesh chunk messages over MeshCore-flashed hardware using the exact same client/server orchestration code that runs Meshtastic today.

---

## Architecture Overview

### Current flow (Meshtastic only)
```
btcmesh_client_cli.py ──► MeshtasticSerialTransport() ──► client/sender.py (TransactionSender)
                                     │
                            meshtastic.serial_interface.SerialInterface
                            (sync, pubsub "meshtastic.receive" topic)
```

### New flow (this epic)
```
btcmesh_client_cli.py ──► get_transport(args.transport) ──┬──► MeshtasticSerialTransport  (unchanged)
        --transport {meshtastic,meshcore}                 └──► MeshCoreSerialTransport     (new)
                                                                     │
                                                            background asyncio event-loop thread
                                                                     │
                                                            meshcore.MeshCore (asyncio client)
                                                            (create_serial, commands.send_msg,
                                                             subscribe(CONTACT_MSG_RECV))
```
`client/sender.py` / `server/receiver.py` sit above `BaseTransport` and are untouched either way.

### What gets added
- `transport/meshcore_serial.py` - new, this story.
- `transport/factory.py` - new, thin `get_transport(name)` dispatcher (Story 30.3, bundled here since it's tiny and needed to actually exercise 30.1 by hand).
- `--transport` argparse flag on `btcmesh_client_cli.py` / `btcmesh_server_cli.py` (Story 30.3).
- `meshcore` added to `requirements.txt` (bare name, unpinned - matches the existing convention for `meshtastic`, `pyserial`, etc.).
- `tests/test_meshcore_serial_transport.py` - new, mirroring `tests/test_meshtastic_serial_transport.py`'s structure.

### What is explicitly NOT touched in this story
- `core/protocol.py`'s `validate_destination()` - stays as-is for now (still only called for Meshtastic destinations via the CLI's default transport). Generalizing it onto `BaseTransport` is **Story 30.2**, deliberately separated so this story stays reviewable as "does the new transport work" without also changing an existing, working code path.
- `core/meshtastic_utils.py` and GUI device-scanning/dropdown wiring - **Story 30.4**, deferred.
- `scan_for_reconnect_candidates()` - implemented as a no-op returning `[]` for now (see Key Design Decisions #4). MeshCore device discovery is Story 30.4's job.

---

## Implementation Steps

### 1. Add dependency
Add `meshcore` to `requirements.txt` (bare name, no pin, same convention as the rest of the file).

### 2. `transport/meshcore_serial.py` - skeleton and lifecycle

A dedicated background thread owns the asyncio event loop for this transport instance's whole lifetime; every public method bridges into it via `asyncio.run_coroutine_threadsafe(...)` + `future.result(timeout=...)`. This is the asyncio-native equivalent of the same "bounded wait on a background worker" pattern `MeshtasticSerialTransport.send()` already uses today for Issue 21's wedge protection - same *shape*, different primitive.

```python
import asyncio
import threading
from typing import List, Optional

from transport.base import (
    BaseTransport, MessageHandler,
    TransportConnectionError, TransportSendError,
)

class MeshCoreSerialTransport(BaseTransport):
    _CONNECT_TIMEOUT_SECONDS = 15.0
    _SEND_TIMEOUT_SECONDS = 10.0
    _CHECK_ALIVE_TIMEOUT_SECONDS = 20.0
    _BAUD_RATE = 115200

    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._mc = None  # meshcore.MeshCore instance
        self._handler: Optional[MessageHandler] = None
        self._my_public_key: Optional[str] = None

    def _ensure_loop(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._loop_thread.start()

    def _run_coro(self, coro, timeout: float):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)
```

### 3. `connect()`

```python
    def connect(self, device_path: Optional[str] = None) -> None:
        self._ensure_loop()
        try:
            from meshcore import MeshCore  # lazy import, mirrors MeshtasticSerialTransport
        except ImportError as e:
            raise TransportConnectionError(f"meshcore library not installed: {e}") from e

        async def _do_connect():
            return await MeshCore.create_serial(device_path, self._BAUD_RATE)

        try:
            self._mc = self._run_coro(_do_connect(), self._CONNECT_TIMEOUT_SECONDS)
        except Exception as e:
            raise TransportConnectionError(f"Failed to connect to MeshCore device: {e}") from e

        if self._handler is not None:
            self._subscribe()
```

`device_path=None` (auto-detect) needs the same treatment `MeshtasticSerialTransport` gives it - `meshcore_py`'s `create_serial()` has no auto-detect of its own (its `port` parameter is required), so BTCMesh does its own single-candidate detection via `serial.tools.list_ports`.

### 4. `send()`

```python
    def send(self, message: str, destination: str) -> None:
        if self._mc is None:
            raise TransportConnectionError("Not connected")

        async def _do_send():
            return await self._mc.commands.send_msg(destination, message)

        try:
            result = self._run_coro(_do_send(), self._SEND_TIMEOUT_SECONDS)
        except Exception as e:
            raise TransportSendError(f"Send failed or timed out: {e}") from e

        from meshcore import EventType
        if result.type == EventType.ERROR:
            raise TransportSendError(str(result.payload))
```

`destination` is the MeshCore contact's public key (prefix or full hex string) - `send_msg()` accepts a raw public-key string directly per the library's documented usage, so no `get_contacts()` lookup is required on the hot path.

### 5. Incoming messages - `set_message_handler()` / `_subscribe()`

```python
    def set_message_handler(self, handler: MessageHandler) -> None:
        self._handler = handler
        if self._mc is not None:
            self._subscribe()

    def remove_message_handler(self) -> None:
        self._handler = None

    def _subscribe(self) -> None:
        from meshcore import EventType

        async def _on_event(event):
            data = event.payload
            text = data.get("text")
            sender = data.get("pubkey_prefix")
            if text is not None and self._handler is not None:
                self._handler(text, sender)

        self._mc.subscribe(EventType.CONTACT_MSG_RECV, _on_event)
```

`_on_event` runs on the loop thread and calls `self._handler(...)` directly and synchronously from there. This matches how Meshtastic's own `pubsub` already invokes `_on_meshtastic_receive` from *its* background reader thread today - `client/sender.py`'s `threading.Event`-based synchronization is already safe against a handler firing from an arbitrary background thread, so nothing upstream needs to change.

### 6. `disconnect()`, `check_alive()`, `scan_for_reconnect_candidates()`, `is_connected`, `local_node_id`

- `disconnect()`: bridge `await self._mc.disconnect()` the same way as `send()`; always safe to call even if not connected (per `BaseTransport` contract).
- `check_alive(timeout_seconds=None)`: send a lightweight round-trip command (`commands.send_device_query()`) with the same bridge pattern; **never raises**, returns `False` on any exception or timeout, matching `BaseTransport`'s contract.
- `scan_for_reconnect_candidates()`: returns `[]` for now (see Key Design Decision #4).
- `is_connected`: `self._mc is not None`.
- `local_node_id`: returns `self._my_public_key` (or a shortened prefix, for parity with Meshtastic's `!hex8` display convention) once connect resolves it.

### 7. Tests - `tests/test_meshcore_serial_transport.py`

Mirror `tests/test_meshtastic_serial_transport.py`'s structure, mocking `sys.modules['meshcore']` the same way the existing suite mocks `sys.modules['meshtastic']`. The one real difference: mocked async methods need `unittest.mock.AsyncMock` instead of plain `MagicMock`, since every meaningful call is `await`-ed.

### 8. `transport/factory.py` + CLI wiring (Story 30.3, bundled)

```python
# transport/factory.py
from transport.base import BaseTransport
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.meshcore_serial import MeshCoreSerialTransport

def get_transport(name: str) -> BaseTransport:
    if name == "meshtastic":
        return MeshtasticSerialTransport()
    if name == "meshcore":
        return MeshCoreSerialTransport()
    raise ValueError(f"Unknown transport: {name}")
```

Add `--transport {meshtastic,meshcore}` (default `meshtastic`) to both `btcmesh_client_cli.py` and `btcmesh_server_cli.py`, replacing the hardcoded `MeshtasticSerialTransport()` construction with `get_transport(args.transport)`. GUIs stay hardcoded to Meshtastic for now (Story 30.4).

---

## Critical Files & Functions to Reference

| File | Role |
|---|---|
| `transport/base.py` | `BaseTransport` ABC - the contract every method above must satisfy exactly (signatures, exception types, "never raises" guarantees). |
| `transport/meshtastic_serial.py` | Pattern to mirror for lifecycle, error mapping, and the "bounded wait on a background worker" send-timeout shape. |
| `transport/power_control.py` | Referenced by `scan_for_reconnect_candidates()` on the Meshtastic side - not used by MeshCore yet (Story 30.4). |
| `client/sender.py:291` (`validate_destination` call site) | Untouched this story; Story 30.2's target. |
| `core/constants.py` | `MAX_TOTAL_CHUNKS`'s docstring derives the value from Meshtastic's LongFast airtime budget - flag for re-validation against MeshCore's framing in a later story, not blocking this one. |
| `tests/test_meshtastic_serial_transport.py` | Structure and mocking pattern to mirror for the new test file. |
| `requirements.txt` | Add `meshcore`. |

---

## Key Design Decisions

1. **Background asyncio event-loop thread, bridged via `run_coroutine_threadsafe`.** Alternative considered: `asyncio.run()` per call - rejected, since it would tear down and rebuild the event loop (and the underlying connection's async context) on every single send, and can't support a persistent event-subscription callback for incoming messages at all.

2. **Handler invoked directly from the loop thread, no queue/marshaling layer.** Matches the concurrency model Meshtastic's `pubsub` callback already uses today (invoked from Meshtastic's own background reader thread) - `client/sender.py`'s `threading.Event` synchronization already tolerates this, so no new thread-safety work is needed upstream.

3. **Destination-format validation stays out of scope for this story.** `core/protocol.py::validate_destination()` keeps its Meshtastic-only `!hex8` check; MeshCore destinations simply aren't validated by that path yet. Story 30.2 moves validation onto `BaseTransport` per-transport. Rejected alternative: block Story 30.1 on doing 30.2 first - rejected because it needlessly couples "does the transport work" to an unrelated refactor of existing, working code.

4. **`scan_for_reconnect_candidates()` returns `[]` for MeshCore.** `BaseTransport`'s contract explicitly allows this ("Returns an empty list rather than raising if scanning isn't possible"), and `core/meshtastic_utils.py`'s scanning logic is deeply Meshtastic-API-shaped - building a MeshCore equivalent is real, separable work (Story 30.4), not needed to prove the transport itself works.

5. **`send_msg()` takes a raw public-key string as `destination`, no contact-list lookup.** Confirmed from the library's documented usage (`send_msg(contact['public_key'], text)` works directly with a string). Avoids needing `get_contacts()` + a name/prefix-matching step on every send.

---

## Implementation Order

0. Create branch `epic-9-meshcore-support` off current `master`; this and all subsequent MeshCore story branches target it, not `master` directly (unrelated hotfixes keep landing on `master` in parallel, per existing `epic-7-reliability-hardening` precedent).
1. Add `meshcore` to `requirements.txt`, confirm it installs cleanly.
2. Write `transport/meshcore_serial.py` skeleton + `connect()`/`disconnect()`, confirming the exact async API surface against the actually-installed library source.
3. Implement `send()` + `_subscribe()`/incoming-message handling.
4. Implement `check_alive()`, `scan_for_reconnect_candidates()` stub, properties.
5. Write `tests/test_meshcore_serial_transport.py`.
6. Add `transport/factory.py` + `--transport` CLI flag on both CLIs (Story 30.3).
7. Manual smoke test against real MeshCore-flashed hardware (once available) - informal at this stage; a proper `scripts/hw_tests/` script is Story 30.5.

---

## Verification

- `python -m unittest tests.test_meshcore_serial_transport` - new suite passes.
- `python -m unittest discover -s tests -p 'test_*.py'` - full suite still green, confirming zero regression to the Meshtastic path.
- Manual: `python btcmesh_client_cli.py --transport meshcore --destination <pubkey> --tx <hex> --dry-run` runs without error against a mocked/no-op path; real send once hardware is flashed.
- Confirm default (`--transport` omitted) still exercises `MeshtasticSerialTransport` unchanged.

## Files to Create/Modify

| File | Change |
|---|---|
| `transport/meshcore_serial.py` | New - `MeshCoreSerialTransport(BaseTransport)`. |
| `transport/factory.py` | New - `get_transport(name)`. |
| `tests/test_meshcore_serial_transport.py` | New. |
| `requirements.txt` | Add `meshcore`. |
| `btcmesh_client_cli.py`, `btcmesh_server_cli.py` | Add `--transport` flag, use `get_transport()`. |
| `project/tasks.txt` | Add Epic 9 / Story 30.1-30.5 entries. |

## Success Criteria

- [x] `MeshCoreSerialTransport` implements every `BaseTransport` method with matching exception contracts.
- [x] New unit test suite passes; full existing suite has zero regressions.
- [x] `--transport meshcore` is selectable from both CLIs; default behavior for existing users is unchanged.
- [x] No changes required to `client/sender.py` or `server/receiver.py`.

---

## Implementation Completion

**Status:** Story 30.1 and Story 30.3 complete (bundled together, as the plan anticipated). Story 30.2 (destination-format validation refactor) remains open, with a narrow interim stopgap described below.

**API verification:** Before writing `transport/meshcore_serial.py`, every `meshcore_py` method signature this plan relies on (`MeshCore.create_serial`, `commands.send_msg`, `commands.send_device_query`, `subscribe`, `self_info`, `Subscription.unsubscribe`, the `EventType`/`Event` shapes, and the `CONTACT_MSG_RECV`/`SELF_INFO` payload dict keys) was confirmed directly against the library's GitHub source rather than guessed from secondary docs. After implementation, `pip install meshcore` (2.3.9.1) and `inspect.signature()` against the real installed package confirmed every signature matched exactly - no surprises, no rework needed.

**Deviations from the plan / additions beyond it:**
- `disconnect()` also tears down the background asyncio loop and thread entirely (`loop.call_soon_threadsafe(loop.stop)`, join, `loop.close()`), not just the `meshcore` client connection - the plan's code sketch only showed the client disconnect. Without this, repeated connect()/disconnect() cycles (e.g. DeviceWatchdog recovery retries) would each leak a running loop thread.
- `local_node_id` truncates the full 32-byte public key to the same 6-byte/12-hex-char prefix MeshCore uses to identify contacts elsewhere in its protocol (incoming messages report `pubkey_prefix`, not the full key) - the plan left this detail open ("or a shortened prefix").
- `_autodetect_port()` (single-serial-port detection via `serial.tools.list_ports`) was designed and implemented in full - the plan flagged this as "an open item to resolve while implementing," not blocking.
- Story 30.3's CLI wiring needed one small addition the plan didn't call out: `btcmesh_client_cli.py`'s `cli_main()` now skips the Meshtastic-only `validate_destination()` call when `--transport meshcore` is selected (a non-`!`-prefixed MeshCore public key would otherwise always fail that check). This is a narrow, explicit stopgap - Story 30.2's actual `BaseTransport.validate_destination()` refactor is still open. `meshcore_py`'s own `send_msg()` still rejects a malformed destination at send time either way. The server CLI's Meshtastic-only relay-board check and `MESHTASTIC_SERIAL_PORT` env fallback were also guarded behind `transport_name == "meshtastic"` for the same reason.
- Added `transport/factory.py`'s `TRANSPORT_DISPLAY_NAMES` (not in the original plan) so user-facing log/print messages read "MeshCore"/"Meshtastic" rather than the raw lowercase `--transport` argument value, on both CLIs.

**Test results:** `tests/test_meshcore_serial_transport.py` - 38 new tests, all passing. Full suite: 906 tests, all passing, both before and after `pip install meshcore` (i.e. with the library both mocked and genuinely present). `tests/test_btcmesh_client_cli.py` and `tests/test_btcmesh_server_cli.py` were updated to patch `get_transport` instead of `MeshtasticSerialTransport` directly, plus new coverage for the `--transport` flag and the MeshCore-specific interim behaviors above.

**Manual verification:** Run against the real installed `meshcore` package (not mocked) on this machine: `--transport meshcore --dry-run` previews chunking correctly without attempting a connection; a real (non-dry-run) connection attempt correctly walked the full `_autodetect_port()` → `TransportConnectionError` → CLI error-reporting path, surfacing "Multiple serial devices detected" (this machine has more than one serial port) exactly as designed. No MeshCore-flashed hardware was available to verify an actual send/receive round-trip - that remains for Story 30.5's real-hardware verification once hardware exists.

**Next steps:** Story 30.2 (`BaseTransport.validate_destination()` refactor, replacing both the CLI stopgap and `core/protocol.py`'s Meshtastic-only free function), then Story 30.4 (MeshCore device scanning/GUI wiring) and Story 30.5 (real-hardware verification script).
