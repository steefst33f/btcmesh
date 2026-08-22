#!/usr/bin/env python3
"""
BTCMesh Meshtastic Utilities - Shared utilities for working with Meshtastic devices.

This module provides device scanning, node information retrieval, and formatting
functions used by CLI, GUI, and server components.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict


def scan_meshtastic_devices() -> List[str]:
    """Scan for available Meshtastic devices.

    Returns:
        List of device paths (e.g., ['/dev/ttyUSB0', '/dev/ttyACM0']).
        Returns empty list if no devices found or meshtastic not installed.
    """
    try:
        from meshtastic.util import blacklistVids, eliminate_duplicate_port
        import serial.tools.list_ports

        # meshtastic.util.findPorts() only falls back to "not blacklisted" ports
        # when zero whitelisted-VID ports are found, so a whitelisted device
        # (e.g. Espressif's 0x303a) silently hides any other connected device
        # whose VID isn't on the whitelist (e.g. Seeed's 0x2886). Filter by the
        # (narrow) blacklist ourselves instead, so all real devices are found.
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
    """A Meshtastic-candidate serial port and its identifying info.

    serial_number is best-effort, not guaranteed-unique or even present -
    reliability is chip-dependent (confirmed empirically: CH340-based
    boards report None; some CP2102 boards share an identical factory-
    default value across multiple physical devices). Callers must not
    assume it uniquely identifies a device on its own.
    """
    path: str
    serial_number: Optional[str]
    description: Optional[str]


def scan_meshtastic_devices_detailed() -> List[DeviceInfo]:
    """Like scan_meshtastic_devices(), but also returns each device's
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


# A freshly enumerated serial port (or one just released by another
# process) can transiently fail to open for a moment - matches the same
# transient-failure pattern btcmesh_client_gui.py's _init_meshtastic()
# already retries around. Confirmed against real hardware (see Story 27.2
# manual verification, 2026-08-22): a Seeed device that connected fine
# moments earlier failed instantly on a single probe attempt. Kept short
# (2 attempts) since every non-Meshtastic candidate (e.g. the Story 26.7
# relay board's own port) also pays this cost, and those fail fast anyway.
PROBE_MAX_ATTEMPTS = 2
PROBE_RETRY_DELAY_SECONDS = 1.5


def probe_device_node_id(path: str) -> Optional[str]:
    """Briefly connect to a candidate serial port to learn its Meshtastic
    node ID, then disconnect. Returns None (never raises) if the path
    isn't a genuine Meshtastic device, is already in use, or the
    connection attempt still fails/times out after PROBE_MAX_ATTEMPTS -
    e.g. a false-positive candidate from scan_meshtastic_devices()'s
    VID-blacklist filtering, such as the Story 26.7 relay board's own
    serial port, which speaks a completely different protocol.

    Lazy-imports MeshtasticSerialTransport (matching this module's
    existing dependency style) to avoid a hard import-time dependency
    from core/ on transport/.
    """
    import time

    from transport.meshtastic_serial import MeshtasticSerialTransport
    from transport.base import TransportConnectionError

    for attempt in range(PROBE_MAX_ATTEMPTS):
        transport = MeshtasticSerialTransport()
        try:
            transport.connect(path)
            return transport.local_node_id
        except TransportConnectionError:
            if attempt < PROBE_MAX_ATTEMPTS - 1:
                time.sleep(PROBE_RETRY_DELAY_SECONDS)
        finally:
            transport.disconnect()

    return None


def format_device_display(path: str, node_id: Optional[str]) -> str:
    """Format a device path and its (possibly not-yet-known) node ID for
    display in a dropdown.

    Returns:
        'path' alone if node_id isn't known yet/unavailable, else
        'path (node_id)' - e.g. '/dev/cu.usbserial-0001 (!7c5b4418)'.
    """
    return f"{path} ({node_id})" if node_id else path


def get_own_node_id(iface) -> Optional[str]:
    """Get the node ID of the connected Meshtastic device.

    Args:
        iface: Meshtastic interface with myInfo attribute

    Returns:
        Node ID string (e.g., '!abcd1234') or None if not connected.
    """
    if not iface or not iface.myInfo:
        return None
    try:
        node_num = iface.myInfo.my_node_num
        return f"!{node_num:08x}"
    except (AttributeError, TypeError):
        return None


def get_own_node_name(iface) -> Optional[str]:
    """Get the name of the connected device's own node.

    Args:
        iface: Meshtastic interface with nodes dictionary and myInfo

    Returns:
        The node's longName or shortName, or None if not available.
    """
    if not iface or not iface.myInfo:
        return None

    try:
        own_node_num = iface.myInfo.my_node_num
        own_node_id = f"!{own_node_num:08x}"

        if not iface.nodes or own_node_id not in iface.nodes:
            return None

        node_data = iface.nodes[own_node_id]
        user = node_data.get('user', {}) if isinstance(node_data, dict) else {}
        long_name = user.get('longName', '') if isinstance(user, dict) else ''
        short_name = user.get('shortName', '') if isinstance(user, dict) else ''

        name = long_name or short_name
        return name if name else None
    except (AttributeError, TypeError, KeyError):
        return None


def get_known_nodes(iface, exclude_own: bool = True) -> List[Dict]:
    """Get list of known nodes from a Meshtastic interface.

    Args:
        iface: Meshtastic interface with nodes dictionary
        exclude_own: Whether to exclude the device's own node (default True)

    Returns:
        List of dicts with keys: id, name, lastHeard, is_recent
        Sorted by lastHeard descending (most recent first).
    """
    import time

    if not iface or not iface.nodes:
        return []

    # Get own node number to filter out
    own_node_num = None
    if exclude_own and iface.myInfo:
        own_node_num = iface.myInfo.my_node_num

    nodes = []
    now = int(time.time())
    hours_24 = 24 * 60 * 60

    for node_id, node_data in iface.nodes.items():
        # Skip own node by comparing node_id hex to own_node_num
        if own_node_num is not None:
            try:
                node_num = int(node_id.lstrip('!'), 16)
                if node_num == own_node_num:
                    continue
            except (ValueError, AttributeError):
                pass

        # Extract user info
        user = node_data.get('user', {}) if isinstance(node_data, dict) else {}
        long_name = user.get('longName', '') if isinstance(user, dict) else ''
        short_name = user.get('shortName', '') if isinstance(user, dict) else ''

        # Use longName, or shortName, or node_id as fallback
        name = long_name or short_name or node_id

        # Get lastHeard timestamp. dict.get()'s default only applies when the
        # key is missing, not when it's present but None (e.g. a node the
        # device knows about but has never actually heard a packet from) -
        # coerce that case to 0 too, otherwise sorting below crashes trying
        # to compare None against other nodes' int timestamps.
        last_heard = (node_data.get('lastHeard') or 0) if isinstance(node_data, dict) else 0

        # Determine if node was seen in last 24 hours
        is_recent = (now - last_heard) < hours_24 if last_heard else False

        nodes.append({
            'id': node_id,
            'name': name,
            'lastHeard': last_heard,
            'is_recent': is_recent,
        })

    # Sort by lastHeard descending (most recent first)
    nodes.sort(key=lambda n: n['lastHeard'], reverse=True)

    return nodes


def format_node_display(node: Dict) -> str:
    """Format a node dict for display in a dropdown or list.

    Args:
        node: Dict with keys: id, name, lastHeard, is_recent

    Returns:
        Formatted string: 'Name (!nodeid)'
    """
    return f"{node['name']} ({node['id']})"


def get_node_by_id(iface, node_id: str) -> Optional[Dict]:
    """Get a specific node's information by its ID.

    Args:
        iface: Meshtastic interface with nodes dictionary
        node_id: The node ID to look up (e.g., '!abcd1234')

    Returns:
        Dict with node information or None if not found.
    """
    if not iface or not iface.nodes:
        return None

    node_data = iface.nodes.get(node_id)
    if not node_data:
        return None

    user = node_data.get('user', {}) if isinstance(node_data, dict) else {}
    long_name = user.get('longName', '') if isinstance(user, dict) else ''
    short_name = user.get('shortName', '') if isinstance(user, dict) else ''

    return {
        'id': node_id,
        'name': long_name or short_name or node_id,
        'longName': long_name,
        'shortName': short_name,
        'lastHeard': node_data.get('lastHeard', 0) if isinstance(node_data, dict) else 0,
    }
