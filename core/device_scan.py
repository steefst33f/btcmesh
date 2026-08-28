#!/usr/bin/env python3
"""
BTCMesh Device Scanning - serial-port enumeration shared by every mesh
transport (Meshtastic, MeshCore, ...).

Candidate-port enumeration has no transport-protocol content: it's
serial.tools.list_ports.comports() filtered by a generic "known non-radio
USB-serial VID" blacklist and deduped across OS-level path aliases for the
same physical device. That's true regardless of which mesh firmware a
given board happens to be running, so it lives here once rather than
being duplicated per transport. Per-transport identity probing (actually
connecting to learn a device's protocol-specific node ID/name) is NOT
here - see core/meshtastic_utils.py's and core/meshcore_utils.py's own
probe_device_identity() for that.
"""
from dataclasses import dataclass
from typing import Optional, List


def scan_serial_devices() -> List[str]:
    """Scan for available candidate serial devices.

    Returns:
        List of device paths (e.g., ['/dev/ttyUSB0', '/dev/ttyACM0']).
        Returns empty list if no devices found or meshtastic not installed.
    """
    try:
        from meshtastic.util import blacklistVids, eliminate_duplicate_port
        import serial.tools.list_ports

        # meshtastic.util.findPorts() only falls back to "not blacklisted"
        # ports when zero whitelisted-VID ports are found, so a
        # whitelisted device (e.g. Espressif's 0x303a) silently hides any
        # other connected device whose VID isn't on the whitelist (e.g.
        # Seeed's 0x2886). Filter by the (narrow) blacklist ourselves
        # instead, so all real devices are found.
        ports = sorted(
            port.device
            for port in serial.tools.list_ports.comports()
            if port.vid is not None and port.vid not in blacklistVids
        )
        return eliminate_duplicate_port(ports)
    except ImportError:
        return []
    except Exception:
        return []


@dataclass
class DeviceInfo:
    """A candidate serial port and its identifying info.

    serial_number is best-effort, not guaranteed-unique or even present -
    reliability is chip-dependent (confirmed empirically: CH340-based
    boards report None; some CP2102 boards share an identical factory-
    default value across multiple physical devices). Callers must not
    assume it uniquely identifies a device on its own.
    """
    path: str
    serial_number: Optional[str]
    description: Optional[str]


def scan_serial_devices_detailed() -> List[DeviceInfo]:
    """Like scan_serial_devices(), but also returns each device's
    serial_number/description for stable-identity matching (Story 26.4's
    DeviceWatchdog, to recognize a device across re-enumeration after a
    power cycle even if its OS-assigned path changes).

    Returns:
        List of DeviceInfo. Empty list if no devices found or meshtastic
        not installed.
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


@dataclass
class ProbedDevice:
    """Result of probing a candidate serial port for its transport-specific
    identity (node ID + configured name). Fields are None together (never
    a bare None return from a probe_device_identity()) if the path isn't a
    genuine/reachable device for the transport being probed - callers
    never need a None-check before destructuring."""
    node_id: Optional[str]
    name: Optional[str]


def format_device_display(path: str, node_id: Optional[str], name: Optional[str] = None) -> str:
    """Format a device path and its (possibly not-yet-known) identity for
    display in a dropdown.

    Returns:
        'path' alone if neither is known yet; 'path (node_id)' if only
        the node_id is known; 'name (node_id)' if both are known - e.g.
        'Meshtastic 4418 (!7c5b4418)'; 'name' alone if only a name is
        known with no node_id - e.g. a probe_device_identity()'s relay-
        board result (RELAY_BOARD_NAME, per-transport), which has no mesh
        protocol identity to show.
    """
    if node_id and name:
        return f"{name} ({node_id})"
    if node_id:
        return f"{path} ({node_id})"
    if name:
        return name
    return path
