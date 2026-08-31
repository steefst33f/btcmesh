"""Transport selection by name, for CLI/GUI entry points."""
from __future__ import annotations

from transport.base import BaseTransport
from transport.meshcore_serial import MeshCoreSerialTransport
from transport.meshtastic_serial import MeshtasticSerialTransport

TRANSPORT_CHOICES = ("meshtastic", "meshcore")

# Display names for user-facing log/print messages (CLI/GUI), keyed by the
# same values as TRANSPORT_CHOICES.
TRANSPORT_DISPLAY_NAMES = {
    "meshtastic": "Meshtastic",
    "meshcore": "MeshCore",
}


def get_transport(name: str) -> BaseTransport:
    """Return a new transport instance for the given name.

    Args:
        name: One of TRANSPORT_CHOICES.

    Raises:
        ValueError: If name is not a known transport.
    """
    if name == "meshtastic":
        return MeshtasticSerialTransport()
    if name == "meshcore":
        return MeshCoreSerialTransport()
    raise ValueError(f"Unknown transport: {name}")
