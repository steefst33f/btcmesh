"""Device recovery orchestration for EPIC 5 (Device Power-Cycle Recovery).

DeviceWatchdog detects a wedged Meshtastic device via two complementary
signals - repeated send/connect failures, and a periodic liveness
heartbeat (transport.check_alive()) - and drives the recovery cycle:
disconnect, power-cycle, wait for genuine re-enumeration, reconnect.

See project/plans/story_26_4.md for the full design rationale.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.meshtastic_utils import scan_meshtastic_devices_detailed
from transport.base import BaseTransport, TransportConnectionError
from transport.power_control import BasePowerControl, PowerControlError


@dataclass
class RecoveryOutcome:
    success: bool
    new_device_path: Optional[str] = None
    error: Optional[str] = None


class DeviceWatchdog:
    """Caller-driven - has no background thread of its own. Call tick()
    periodically (e.g. once per second) from the same loop that already
    drives other polling (matching TransactionReceiver.check_timeouts()'s
    existing pattern), and record_success()/record_failure() around each
    send/receive/connect attempt. This keeps every check_alive()/transport/
    power_control call on a single caller-controlled thread - check_alive()
    can block up to ~20s in the unhealthy case, so this must never run
    concurrently with other access to the same transport.
    """

    def __init__(
        self,
        transport: BaseTransport,
        power_control: Optional[BasePowerControl],
        device_node_id: Optional[str],
        max_consecutive_failures: int = 3,
        heartbeat_interval_seconds: float = 60.0,
        max_reenumerate_wait_seconds: float = 60.0,
        on_recovery_attempt: Optional[Callable[[], None]] = None,
        on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
        on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
    ):
        """
        Args:
            device_node_id: the Meshtastic node ID (e.g. '!aee5ab3c') of
                the device this watchdog is guarding - captured from the
                transport's own local_node_id while it was still working.
                This is the authoritative identity check during recovery
                (see _try_candidate); OS-level path/serial_number are not
                trustworthy enough on their own (chip-dependent, and a
                device can re-enumerate under a different path). If None,
                any device that successfully connects during recovery is
                accepted - only safe when exactly one Meshtastic device is
                ever expected on this machine (the normal single-device
                deployment; see Story 26.7).
        """
        self._transport = transport
        self._power_control = power_control
        self._device_node_id = device_node_id
        self._max_consecutive_failures = max_consecutive_failures
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._max_reenumerate_wait_seconds = max_reenumerate_wait_seconds
        self._on_recovery_attempt = on_recovery_attempt
        self._on_recovered = on_recovered
        self._on_recovery_failed = on_recovery_failed

        self._consecutive_failures = 0
        self._last_heartbeat_time = 0.0

    def record_success(self) -> None:
        """Call after any successful send/receive/connect - resets the
        consecutive-failure counter."""
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Call after any failed send/connect. Trips recovery once
        max_consecutive_failures is reached."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._max_consecutive_failures:
            self._recover()

    def tick(self, now: float) -> None:
        """Only performs the (potentially slow) liveness check once
        heartbeat_interval_seconds has elapsed since the last one."""
        if now - self._last_heartbeat_time < self._heartbeat_interval_seconds:
            return
        self._last_heartbeat_time = now
        if not self._transport.check_alive():
            self._recover()

    def _recover(self) -> None:
        if self._on_recovery_attempt:
            self._on_recovery_attempt()

        self._transport.disconnect()

        if self._power_control is None:
            self._fail("No power control configured - cannot recover automatically")
            return

        try:
            self._power_control.power_cycle()
        except PowerControlError as e:
            self._fail(f"Power cycle failed: {e}")
            return

        matched_path = self._wait_for_device()
        if matched_path is None:
            self._fail("Device did not reappear within the wait window")
            return

        # _try_candidate() already connected as part of confirming the
        # match - nothing more to do here.
        self._consecutive_failures = 0
        outcome = RecoveryOutcome(success=True, new_device_path=matched_path)
        if self._on_recovered:
            self._on_recovered(outcome)

    def _wait_for_device(self) -> Optional[str]:
        """Poll for the device's reappearance with backoff, connecting to
        each visible candidate and checking its real Meshtastic node ID -
        the only fully authoritative identity signal (OS-level path and
        USB serial_number are both unreliable - see Story 26.3's
        findings)."""
        deadline = time.time() + self._max_reenumerate_wait_seconds
        delay = 2.0
        while time.time() < deadline:
            for candidate in scan_meshtastic_devices_detailed():
                if self._try_candidate(candidate.path):
                    return candidate.path
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
        return None

    def _try_candidate(self, path: str) -> bool:
        """Connect to a candidate path and check whether it's genuinely
        our device via its real Meshtastic node ID - not just whether the
        path connects at all, since a stale path can appear in scan
        results before the device is functionally ready, and a machine
        can have more than one Meshtastic-like device connected.

        Leaves the transport connected on a match (the caller doesn't
        need to reconnect); disconnects again on a mismatch.
        """
        try:
            self._transport.connect(path)
        except TransportConnectionError:
            return False

        if (
            self._device_node_id is None
            or self._transport.local_node_id == self._device_node_id
        ):
            return True

        self._transport.disconnect()
        return False

    def _fail(self, message: str) -> None:
        if self._on_recovery_failed:
            self._on_recovery_failed(RecoveryOutcome(success=False, error=message))
