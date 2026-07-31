"""Abstract power-cycling interface for recovering a wedged USB device.

Part of EPIC 5 (Device Power-Cycle Recovery / Watchdog) - see
project/plans/story_26_1.md for the full epic design and
project/issues.txt Issue 12/16 for the real-world lockups this exists to
recover from automatically instead of requiring a human to physically
unplug/replug the device.
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from typing import Optional

import serial


class PowerControlError(Exception):
    """Raised when a power-cycle attempt fails."""
    pass


class BasePowerControl(ABC):
    """Abstract interface for cutting and restoring power to a device.

    Concrete backends: UhubctlPowerControl (below) for uhubctl-compatible
    hubs; a DIY relay-based backend (Story 26.7) is planned as a fallback
    for hubs that don't support software power control at all.
    """

    @abstractmethod
    def power_cycle(self, off_seconds: float = 15.0) -> None:
        """Cut power, wait off_seconds, then restore power.

        Args:
            off_seconds: How long to leave power off before restoring.

        Raises:
            PowerControlError: If the power-cycle attempt fails.
        """
        ...


class UhubctlPowerControl(BasePowerControl):
    """Power-cycles a hub location via the `uhubctl` command-line tool.

    Real hardware verified for this project (see Issue 12/16 and
    project/plans/story_26_1.md's Open Questions) reports as a "ganged"
    hub - all ports share one power switch, with no independent per-port
    control - rather than a "ppps" (per-port power switching) hub. uhubctl
    also refuses to operate on non-ppps hubs at all unless told to
    --force it, so this always passes that flag.

    Because of the ganged limitation, `port` is only meaningful on a
    genuinely ppps-capable hub - on a ganged hub, cycling any port cycles
    every device on that hub together. Omit `port` (the default) to
    explicitly cycle the whole hub location, which is the only operation
    a ganged hub actually supports; only pass `port` if the target hub is
    confirmed ppps-capable via `uhubctl -f` (or plain `uhubctl`, which
    lists ppps hubs without needing --force).
    """

    def __init__(self, location: str, port: Optional[int] = None):
        self._location = location
        self._port = port

    def power_cycle(self, off_seconds: float = 15.0) -> None:
        cmd = [
            "uhubctl", "--force",
            "-l", self._location,
            "-a", "cycle",
            "-d", str(off_seconds),
        ]
        if self._port is not None:
            cmd += ["-p", str(self._port)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=off_seconds + 10,
            )
        except FileNotFoundError:
            raise PowerControlError("uhubctl not found - install it (e.g. brew install uhubctl)")
        except subprocess.TimeoutExpired:
            raise PowerControlError(f"uhubctl timed out after {off_seconds + 10}s")

        if result.returncode != 0:
            raise PowerControlError(
                (result.stderr or result.stdout or "uhubctl failed").strip()
            )


class SerialRelayPowerControl(BasePowerControl):
    """Power-cycles one channel of a companion ESP32 relay board over serial.

    See hardware/power_relay_firmware/power_relay.ino for the firmware this
    talks to, and project/plans/story_26_7.md for why this exists: not every
    USB hub genuinely cuts VBUS power when uhubctl asks it to (see Issue 19),
    so this DIY relay - spliced into a device's own VBUS wire only - gives a
    hardware-independent guarantee regardless of what hub is upstream.

    One instance controls one channel (one device), mirroring how
    UhubctlPowerControl is constructed per hub/port. The serial port is
    always explicit - never auto-detected - since this project's own
    device-scanning helper (core.meshtastic_utils.scan_meshtastic_devices(),
    which filters candidates by a VID blacklist rather than a whitelist)
    would otherwise treat this board's own serial port as a false-positive
    device candidate.
    """

    def __init__(self, port: str, channel: int, baudrate: int = 115200):
        self._port = port
        self._channel = channel
        self._baudrate = baudrate

    def power_cycle(self, off_seconds: float = 15.0) -> None:
        command = f"CYCLE {self._channel} {int(off_seconds)}\n"
        timeout = off_seconds + 10

        try:
            with serial.Serial(self._port, self._baudrate, timeout=timeout) as ser:
                ser.write(command.encode("ascii"))
                response = ser.readline().decode("ascii", errors="replace").strip()
        except serial.SerialException as e:
            raise PowerControlError(f"Serial error talking to relay board: {e}")
        except OSError as e:
            raise PowerControlError(f"Failed to open relay serial port: {e}")

        if response == "":
            raise PowerControlError(
                f"Relay board did not respond within {timeout}s"
            )
        if response != "OK":
            raise PowerControlError(f"Relay board error: {response}")
