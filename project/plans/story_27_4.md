# Story 27.4: Display Firmware Version and Hardware Model from Meshtastic Device Probing

## Background

When a Meshtastic device connects, its `iface.metadata` field is populated for free as part of the existing `waitForConfig()` handshake — the same stream that delivers `myInfo`, node list, and channel config. It contains:

- `firmware_version`: a string, e.g. `"2.6.11.60ec05e"`
- `hw_model`: an integer enum mapping to hardware names like `"HELTEC_V3"` or `"SEEED_XIAO_S3"` — convertible via `mesh_pb2.HardwareModel.Name()`

This data is currently read from the wire but immediately discarded. Surfacing it costs zero extra round-trips.

Two use cases:
1. **Probing** (GUI device dropdowns, `probe_device_identity()`): firmware info becomes part of the `ProbedDevice` result, shown in the dropdown label, and logged when the probe completes
2. **Connecting** (transport layer, both GUI and CLI): firmware info is logged at INFO level alongside the existing node-ID log

Hardware model is shown in the dropdown label (next to node name), not just the log panel — during hardware testing with multiple physically connected devices, seeing hardware model + node name together in the dropdown is the fast way to confirm which physical device is selected, without digging through the log. Firmware version is log-only (it changes less usefully at a glance and would make the label noisier); hardware model rarely changes per device and is the discriminating fact during bring-up.

**Logging is scoped to real connects only, not probes** (revised after real-hardware testing 2026-08-26): a device-dropdown scan probes every found device (via `probe_device_identity()`), and the client GUI's `on_device_selected`/`on_refresh_nodes` also do a brief identity-only connect - none of these are the operator actually using the device. Logging firmware/hardware on every one of those is noise (one line per probed device, on every scan). Only the connects that represent genuine use - CLI send, CLI server, GUI Send, GUI Start Server - log firmware/hardware info. `MeshtasticSerialTransport.connect()` gained a `log_firmware_info: bool = False` parameter so probe-only call sites (the default) stay silent, while the four real-use call sites opt in explicitly. The GUI status-log line moved from the per-device probe handler to each app's existing real-connect success message (`'connected'` in the client GUI, `'meshtastic_connected'` in the server GUI). The dropdown's `[HW_MODEL]` tag is unaffected - it still updates from every probe, since that's the whole point of Story 27.4.

## Changed Files

### `core/meshtastic_utils.py`

**`ProbedDevice` dataclass** — add two optional fields with defaults (preserves backward compat; relay board and connection-failure paths need no changes):

```python
@dataclass
class ProbedDevice:
    node_id: Optional[str]
    name: Optional[str]
    firmware_version: Optional[str] = None
    hw_model: Optional[str] = None
```

**New `extract_firmware_info(iface)` helper** — shared by `probe_device_identity()` below, `transport/meshtastic_serial.py`'s `connect()`, and the client GUI's inline connect path, so the metadata-parsing logic lives in exactly one place:

```python
def extract_firmware_info(iface) -> Tuple[Optional[str], Optional[str]]:
    """Extract firmware version and hardware model name from a connected
    interface's metadata (populated for free by the connect handshake's
    waitForConfig()). Returns (None, None) on any missing/unexpected
    metadata shape rather than raising - firmware info is a nice-to-have
    for logging/display, never worth failing a connection over."""
    if iface is None or getattr(iface, "metadata", None) is None:
        return None, None
    try:
        from meshtastic import mesh_pb2
        firmware_version = iface.metadata.firmware_version or None
        hw_model = mesh_pb2.HardwareModel.Name(iface.metadata.hw_model) or None
        return firmware_version, hw_model
    except Exception:
        return None, None
```

**`probe_device_identity()`** — after `transport.connect()` succeeds, extract via the helper before returning:

```python
firmware_version, hw_model = extract_firmware_info(transport._iface)
return ProbedDevice(
    node_id=transport.local_node_id,
    name=get_own_node_name(transport._iface),
    firmware_version=firmware_version,
    hw_model=hw_model,
)
```

**`format_device_display()`** — add an optional `hw_model` param, appended as a bracketed suffix so it reads as a distinct tag from the `(node_id)` parenthetical:

```python
def format_device_display(path: str, node_id: Optional[str], name: Optional[str] = None,
                           hw_model: Optional[str] = None) -> str:
    suffix = f" [{hw_model}]" if hw_model else ""
    if node_id and name:
        return f"{name} ({node_id}){suffix}"
    if node_id:
        return f"{path} ({node_id}){suffix}"
    if name:
        return f"{name}{suffix}"
    return path
```

e.g. `"Meshtastic 4418 (!7c5b4418) [HELTEC_V3]"`. `hw_model` defaults to `None` (no suffix) so every existing call site keeps compiling unchanged until updated.

### `transport/meshtastic_serial.py`

**`connect()`** — gains a `log_firmware_info: bool = False` parameter. Only when the caller opts in does it lazy-import `extract_firmware_info` (matching this file's existing lazy-import style, e.g. its `scan_meshtastic_devices_detailed` import) and extend the existing success log (currently just node ID) with firmware version and hardware model:

```python
def connect(self, device_path=None, log_firmware_info: bool = False) -> None:
    ...
    firmware_suffix = ""
    if log_firmware_info:
        from core.meshtastic_utils import extract_firmware_info
        firmware_version, hw_model = extract_firmware_info(iface)
        if firmware_version or hw_model:
            firmware_suffix = f", Firmware: {firmware_version or 'unknown'}, Hardware: {hw_model or 'unknown'}"
    logger.info(
        "Connected to Meshtastic device. Node ID: %s%s",
        self._format_node_id(my_node_num),
        firmware_suffix,
    )
```

Default `False` means every existing call site is silent (on the firmware part) unless it explicitly opts in. No import cycle: `core/meshtastic_utils.py` only imports `transport.*` lazily inside function bodies, never at module level, so `transport` importing from `core` (even lazily) is safe.

**Call sites that opt in** (`log_firmware_info=True`) — the four that represent an operator actually using the device, not probing it:
- `btcmesh_client_cli.py`'s `run_send()`
- `btcmesh_server_cli.py`'s `run_server()`
- `btcmesh_client_gui.py`'s `_connect_with_retry()` (only reached from Send)
- `btcmesh_server_gui.py`'s `run_server()` (reached from Start Server)

**Call sites left at the default** (stay silent) — all probe-only connects: `core/meshtastic_utils.py`'s `probe_device_identity()`, and the client GUI's `on_device_selected()`/`on_refresh_nodes()` fetch threads.

### `gui/gui_common.py`

**`probe_devices_in_background()`** — extend the result tuple from 4 to 6 elements:

```python
result_queue.put((
    'device_identity', device['path'],
    identity.node_id, identity.name,
    identity.firmware_version, identity.hw_model,
))
```

**`device_path_from_display()`** and **`refresh_device_spinner_labels()`** — both call `format_device_display()`; update all three call sites to pass `device['hw_model']` (the device dicts, described below, always carry the key).

### `btcmesh_server_gui.py`

**Device dict construction** (`'devices_found'` handler) — add `'firmware_version': None, 'hw_model': None` alongside the existing `'node_id': None, 'name': None`.

**`format_device_display()` call site** — pass `d['hw_model']`.

**`'device_identity'` handler** — destructure firmware fields and store on the device dict only (feeds the dropdown's `[HW_MODEL]` tag). No status-log line here — this handler fires once per probed device on every scan, so logging here would repeat once per device every time the operator hits Scan:

```python
path, node_id, name = result[1], result[2], result[3]
firmware_version = result[4] if len(result) > 4 else None
hw_model = result[5] if len(result) > 5 else None
for device in self.devices:
    if device['path'] == path:
        device['node_id'], device['name'] = node_id, name
        device['firmware_version'], device['hw_model'] = firmware_version, hw_model
        break
```

`len(result) > 4` guard keeps the handler tolerant if any code path still produces a 4-element tuple.

**`run_server()`'s `'meshtastic_connected'` real-connect path** — this is the actual "Start Server" connect (`log_firmware_info=True`), so its data dict and status-log line pick up firmware/hardware instead:

```python
firmware_version, hw_model = extract_firmware_info(transport._iface)
self.result_queue.put((
    'meshtastic_connected',
    {'node_id': ..., 'device': ..., 'node_name': ...,
     'firmware_version': firmware_version, 'hw_model': hw_model},
))
```

and in the `'meshtastic_connected'` handler, the existing "Connected to Meshtastic device: ..." status-log line gets a suffix when present: `" - firmware X, hardware Y"`.

### `btcmesh_client_gui.py`

Three places to update:

1. **Device dict construction** (`'devices_found'` handler) — same `firmware_version`/`hw_model` defaults as the server GUI.

2. **`format_device_display()` call site** — pass `d['hw_model']`.

3. **`'device_identity'` handler** (background probe result) — same as server GUI: store on the device dict only, no status-log line (this also covers `on_device_selected()`'s own identity-probe connect, which puts a `'device_identity'` tuple too - it stays silent, same as the background scan).

4. **`on_device_selected()`'s inline connect** (`fetch_thread`) — extracts firmware info via the shared helper to populate the `'device_identity'` tuple (for the dropdown tag), but its own `transport.connect(path)` call is NOT passed `log_firmware_info=True` - this is still an identity probe (fired on every device selection), not a real send:

```python
node_id = transport.local_node_id
name = get_own_node_name(transport._iface)
firmware_version, hw_model = extract_firmware_info(transport._iface)
self.result_queue.put(('device_identity', path, node_id, name, firmware_version, hw_model))
```

5. **`_connect_with_retry()`** (called only from `on_send_pressed` → the real Send flow) — its `transport.connect(port)` call passes `log_firmware_info=True`.

6. **The `'connected'` result tuple** (pushed right after a successful send-connect) and `process_result()`'s handling of it — extended with `firmware_version`/`hw_model`, appended to the existing "Connected to Meshtastic device: ..." status-log line as `" - firmware X, hardware Y"` when present. This is the client-side equivalent of the server GUI's `'meshtastic_connected'` handling above.

## Tests

### `tests/test_meshtastic_utils.py`

- `test_probed_device_firmware_fields_default_none`: `ProbedDevice(node_id=None, name=None)` has `firmware_version=None`, `hw_model=None`
- `test_extract_firmware_info_from_metadata`: mock `iface.metadata` with `firmware_version="2.6.11"` and `hw_model=47`; assert `("2.6.11", "HELTEC_V3")` (mocking `mesh_pb2.HardwareModel.Name`)
- `test_extract_firmware_info_tolerates_missing_metadata`: `iface.metadata = None` and `iface = None`; assert `(None, None)`, no exception
- `test_probe_device_identity_extracts_firmware_from_metadata`: mock a successful connect with `transport._iface.metadata` set; assert `ProbedDevice.firmware_version`/`hw_model` populated
- `test_format_device_display_includes_hw_model_suffix`: `format_device_display(path, node_id, name, hw_model="HELTEC_V3")` → ends with `" [HELTEC_V3]"`; omitting `hw_model` reproduces today's exact strings (regression guard)

### `tests/test_meshtastic_serial_transport.py`

- `test_connect_logs_firmware_when_opted_in_and_metadata_available`: `connect(path, log_firmware_info=True)` with `iface.metadata` set; assert the log contains the firmware version string
- `test_connect_omits_firmware_by_default_even_with_metadata_available`: `connect(path)` (default `log_firmware_info=False`) with `iface.metadata` set; assert the log has no firmware/hardware suffix - this is the regression guard for the noise complaint
- `test_connect_logs_node_id_when_metadata_absent`: `connect(path, log_firmware_info=True)` with `metadata=None`; node-ID log still fires, no firmware suffix, no exception

## Relay Board

`probe_device_identity()` short-circuits before any connect attempt for relay boards (returns immediately with `RELAY_BOARD_NAME`). These paths never reach the firmware-extraction code, so they continue to return `firmware_version=None, hw_model=None` with no change required — and `format_device_display()`'s name-only branch never gets an `hw_model` suffix in practice for relay boards.

## What Is Not Changed

- `ProbedDevice.node_id` / `ProbedDevice.name` — existing fields, signature, and callers unchanged
- `dedupe_devices_by_node_id()` — deduplication logic unchanged (still keys on `node_id`)
- `check_alive()` — no firmware info needed in the liveness path
- Firmware version is not added to the dropdown label — only hardware model is (see Background)
