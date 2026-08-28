#!/usr/bin/env python3
"""
BTCMesh MeshCore Utilities - Shared utilities for working with MeshCore
devices.

Mirrors core/meshtastic_utils.py's shape (candidate-port enumeration is
shared, see core/device_scan.py; identity probing is transport-specific,
since it means actually speaking each transport's own connect protocol).
Used by CLI, GUI, and server components.
"""
from typing import List

from core.device_scan import DeviceInfo, ProbedDevice, scan_serial_devices, scan_serial_devices_detailed


def scan_meshcore_devices() -> List[str]:
    """Scan for available MeshCore devices.

    Thin wrapper: candidate-port enumeration itself has nothing
    MeshCore-specific about it (see core/device_scan.py) - this name
    exists so MeshCore call sites read symmetrically with
    core.meshtastic_utils.scan_meshtastic_devices().

    Returns:
        List of device paths (e.g., ['/dev/ttyUSB0', '/dev/ttyACM0']).
        Returns empty list if no devices found or meshtastic not installed.
    """
    return scan_serial_devices()


def scan_meshcore_devices_detailed() -> List[DeviceInfo]:
    """Like scan_meshcore_devices(), but also returns each device's
    serial_number/description for stable-identity matching (mirrors
    core.meshtastic_utils.scan_meshtastic_devices_detailed(), used the
    same way by MeshCoreSerialTransport.scan_for_reconnect_candidates()).

    Returns:
        List of DeviceInfo. Empty list if no devices found or meshtastic
        not installed.
    """
    return scan_serial_devices_detailed()


RELAY_BOARD_NAME = "Relay board (not a MeshCore device)"


def probe_device_identity(path: str) -> ProbedDevice:
    """Briefly connect to a candidate serial port to learn its MeshCore
    node ID and configured name, then disconnect. Returns
    ProbedDevice(None, None) (never raises) if the path isn't a genuine
    MeshCore device, is already in use, or the connection attempt
    fails/times out - e.g. a false-positive candidate from
    scan_meshcore_devices()'s VID-blacklist filtering.

    First does a quick check for whether the candidate is specifically
    the Story 26.7 relay board (probe_relay_board_id()) - if so, returns
    immediately instead of attempting the full MeshCore connect at all,
    which could never succeed against it anyway (a completely different
    protocol) and would otherwise cost a full connection timeout for
    nothing - mirrors core.meshtastic_utils.probe_device_identity()'s
    Issue 37 fix. The relay firmware's real hardware-derived unique ID is
    carried as node_id (prefixed `#` rather than MeshCore's public-key-
    prefix hex, so it's never confused with a real node ID at a glance).

    Deliberately single-attempt, no retry - mirrors
    core.meshtastic_utils.probe_device_identity()'s reasoning (a second
    attempt on the same timescale never turns a genuine wedge/timeout
    into a success).

    Lazy-imports MeshCoreSerialTransport/probe_relay_board_id (matching
    core.meshtastic_utils.probe_device_identity()'s dependency style) to
    avoid a hard import-time dependency from core/ on transport/.
    """
    from transport.meshcore_serial import MeshCoreSerialTransport
    from transport.base import TransportConnectionError
    from transport.power_control import probe_relay_board_id

    relay_id = probe_relay_board_id(path)
    if relay_id:
        return ProbedDevice(node_id=f"#{relay_id}", name=RELAY_BOARD_NAME)

    transport = MeshCoreSerialTransport()
    try:
        transport.connect(path)
        return ProbedDevice(
            node_id=transport.local_node_id,
            name=transport.local_node_name,
        )
    except TransportConnectionError:
        return ProbedDevice(node_id=None, name=None)
    finally:
        transport.disconnect()
