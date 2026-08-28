#!/usr/bin/env python3
"""
BTCMesh Meshtastic Utilities - Shared utilities for working with Meshtastic devices.

Identity probing only - candidate-port enumeration has nothing
transport-specific about it and lives directly in core/device_scan.py
(callers use scan_serial_devices()/scan_serial_devices_detailed() for
both transports). This module provides Meshtastic-specific identity
probing, node information retrieval, and formatting functions used by
CLI, GUI, and server components.
"""
from typing import Optional, List, Dict

from core.device_scan import ProbedDevice


RELAY_BOARD_NAME = "Relay board (not a Meshtastic device)"


def probe_device_identity(path: str) -> ProbedDevice:
    """Briefly connect to a candidate serial port to learn its Meshtastic
    node ID, configured name, and hardware/board model, then disconnect.
    Returns ProbedDevice(None, None) (never raises) if the path isn't a
    genuine Meshtastic device, is already in use, or the connection
    attempt fails/times out - e.g. a false-positive candidate from
    core.device_scan's VID-blacklist filtering.

    First does a quick check for whether the candidate is specifically
    the Story 26.7 relay board (probe_relay_board_id(), Issue 37's
    false-positive-half fix) - if so, returns immediately instead of
    attempting the full Meshtastic connect at all, which could never
    succeed against it anyway (a completely different protocol) and
    previously cost a full ~30s connection timeout for nothing. The
    relay firmware's real hardware-derived unique ID is carried as
    node_id (prefixed `#` rather than Meshtastic's `!`, so it's never
    confused with a real node ID at a glance) - this piggybacks on the
    exact same dedupe_devices_by_node_id() mechanism already built for
    Meshtastic devices, correctly collapsing one physical relay board's
    two OS-level aliases while still keeping two *different* physical
    relay boards as separate entries (their chip IDs differ).

    Deliberately single-attempt on the Meshtastic connect itself, no
    retry: a real-hardware test during Story 27.2's manual verification
    (2026-08-22) tried adding a retry after what looked like a fast
    transient failure, but both actual failures observed were genuine
    ~30s connection timeouts (a wedged device, cleared only by a
    physical power cycle) - a second attempt on the same timescale never
    once turned a failure into a success. See Issue 37 in
    project/issues.txt.

    Lazy-imports MeshtasticSerialTransport/probe_relay_board_id (matching
    this module's existing dependency style) to avoid a hard import-time
    dependency from core/ on transport/.
    """
    from transport.meshtastic_serial import MeshtasticSerialTransport
    from transport.base import TransportConnectionError
    from transport.power_control import probe_relay_board_id

    relay_id = probe_relay_board_id(path)
    if relay_id:
        return ProbedDevice(node_id=f"#{relay_id}", name=RELAY_BOARD_NAME)

    transport = MeshtasticSerialTransport()
    try:
        transport.connect(path)
        return ProbedDevice(
            node_id=transport.local_node_id,
            name=get_own_node_name(transport._iface),
            hardware=get_own_node_hardware(transport._iface),
        )
    except TransportConnectionError:
        return ProbedDevice(node_id=None, name=None)
    finally:
        transport.disconnect()


def format_device_display(path: str, node_id: Optional[str], name: Optional[str] = None) -> str:
    """Format a device path and its (possibly not-yet-known) identity for
    display in a dropdown.

    Returns:
        'path' alone if neither is known yet; 'path (node_id)' if only
        the node_id is known; 'name (node_id)' if both are known - e.g.
        'Meshtastic 4418 (!7c5b4418)'; 'name' alone if only a name is
        known with no node_id - e.g. probe_device_identity()'s Issue 37
        relay-board result ('Relay board (not a Meshtastic device)'),
        which has no Meshtastic protocol identity to show.
    """
    if node_id and name:
        return f"{name} ({node_id})"
    if node_id:
        return f"{path} ({node_id})"
    if name:
        return name
    return path


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


def get_own_node_hardware(iface) -> Optional[str]:
    """Get the connected device's physical hardware/board model (e.g.
    "HELTEC_V3"), mirroring get_own_node_name()'s exact lookup shape.

    Free to read: it's the same node data get_own_node_name() already
    pulls from, just a different field (hwModel) - no extra round-trip.
    The meshtastic library's own dict conversion already renders this as
    the enum's string name ("UNSET" when the device hasn't reported one),
    not a raw integer.

    Args:
        iface: Meshtastic interface with nodes dictionary and myInfo

    Returns:
        The node's hwModel string, or None if not available/unset.
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
        hw_model = user.get('hwModel', '') if isinstance(user, dict) else ''

        return hw_model if hw_model and hw_model != 'UNSET' else None
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
