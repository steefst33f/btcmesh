"""Device recovery orchestration for EPIC 5 (Device Power-Cycle Recovery).

DeviceWatchdog detects a wedged device via two complementary signals -
repeated send/connect failures, and a periodic liveness heartbeat
(transport.check_alive()) - and drives the recovery cycle: disconnect,
power-cycle, wait for genuine re-enumeration, reconnect. Transport-agnostic
by design: only depends on BaseTransport/BasePowerControl, never on any
concrete transport's implementation details (e.g. Meshtastic-specific
scanning) - see BaseTransport.scan_for_reconnect_candidates().

See project/plans/story_26_4.md for the full design rationale.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

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
        recovery_cooldown_seconds: float = 60.0,
        active_check_timeout_seconds: float = 20.0,
        idle_check_timeout_seconds: float = 300.0,
        on_recovery_attempt: Optional[Callable[[], None]] = None,
        on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
        on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
    ):
        """
        Args:
            device_node_id: the local_node_id of the device this watchdog
                is guarding (format is transport-specific, e.g. Meshtastic's
                '!aee5ab3c') - captured from the transport's own
                local_node_id while it was still working. This is the
                authoritative identity check during recovery (see
                _try_candidate); OS-level path/serial_number are not
                trustworthy enough on their own (chip-dependent, and a
                device can re-enumerate under a different path). If None,
                any device that successfully connects during recovery is
                accepted - only safe when exactly one device is ever
                expected on this machine (the normal single-device
                deployment; see Story 26.7).
            recovery_cooldown_seconds: minimum time to wait after a
                recovery cycle finishes (success or failure) before
                starting another one. Without this, a device that's
                merely slower to reboot than max_reenumerate_wait_seconds
                can get stuck in a self-inflicted loop: a failed cycle
                leaves the transport disconnected, so the very next
                tick()/record_failure() immediately starts another cycle
                (another power cut) right as the device might be about
                to finish booting from the previous one - never giving
                it one clean, uninterrupted window long enough to
                actually come up. Found via real-hardware testing (see
                Issue 20 in project/issues.txt).
            active_check_timeout_seconds: check_alive() timeout used when
                tick()'s session_active is True - short, since every
                second a check blocks eats directly into whether a
                time-sensitive in-flight transfer can complete before the
                client's own retry budget runs out (Issue 46).
            idle_check_timeout_seconds: check_alive() timeout used when
                session_active is False - long, matching this codebase's
                original de-facto behavior (see Issue 46), to avoid
                unnecessary recovery-cycle log noise from a single slow
                round-trip when nothing time-sensitive is happening
                (Story 26.8).
        """
        self._transport = transport
        self._power_control = power_control
        self._device_node_id = device_node_id
        self._max_consecutive_failures = max_consecutive_failures
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._max_reenumerate_wait_seconds = max_reenumerate_wait_seconds
        self._recovery_cooldown_seconds = recovery_cooldown_seconds
        self._active_check_timeout_seconds = active_check_timeout_seconds
        self._idle_check_timeout_seconds = idle_check_timeout_seconds
        self._on_recovery_attempt = on_recovery_attempt
        self._on_recovered = on_recovered
        self._on_recovery_failed = on_recovery_failed

        self._consecutive_failures = 0
        self._last_heartbeat_time = 0.0
        self._last_recovery_finished_time = 0.0

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

    def tick(self, now: float, session_active: bool = False) -> None:
        """Only performs the (potentially slow) liveness check once
        heartbeat_interval_seconds has elapsed since the last one.

        session_active: True while a time-sensitive transfer is actively
        in flight - uses active_check_timeout_seconds (short) instead of
        idle_check_timeout_seconds (long) for that check (Story 26.8).
        The caller decides what "active" means; this class stays
        ignorant of sessions as a concept, matching its transport-only
        design (see class docstring).
        """
        if now - self._last_heartbeat_time < self._heartbeat_interval_seconds:
            return
        self._last_heartbeat_time = now
        timeout = (
            self._active_check_timeout_seconds
            if session_active
            else self._idle_check_timeout_seconds
        )
        if not self._transport.check_alive(timeout_seconds=timeout):
            self._recover()

    def _recover(self) -> None:
        now = time.time()
        if now - self._last_recovery_finished_time < self._recovery_cooldown_seconds:
            # Still cooling down from the last attempt - skip silently
            # rather than hammering a device that may just need a clean,
            # uninterrupted window to finish booting (Issue 20).
            return
        try:
            self._recover_once()
        finally:
            self._last_recovery_finished_time = time.time()

    def _recover_once(self) -> None:
        if self._on_recovery_attempt:
            self._on_recovery_attempt()

        self._transport.disconnect()

        # Try an immediate, single reconnect pass before cutting power at
        # all - the device may have already come back on its own (e.g.
        # during the cooldown window since a previous failed cycle), and
        # power-cycling it again would just interrupt it needlessly
        # (Issue 20: repeatedly cutting power right as a slow-to-enumerate
        # device is finishing its boot is what defeats recovery).
        matched_path = self._try_reconnect_without_power_cycle()

        if matched_path is None:
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

    def _try_reconnect_without_power_cycle(self) -> Optional[str]:
        """A single, immediate pass over currently-visible candidates - no
        power cycle, no backoff/polling. Used only to skip an unnecessary
        power cut when the device is already back and reachable."""
        for path in self._transport.scan_for_reconnect_candidates():
            if self._try_candidate(path):
                return path
        return None

    def _wait_for_device(self) -> Optional[str]:
        """Poll for the device's reappearance with backoff, connecting to
        each candidate the transport reports (transport-specific - see
        BaseTransport.scan_for_reconnect_candidates()) and checking its
        real node ID via local_node_id - the only fully authoritative
        identity signal (OS-level path and USB serial_number are both
        unreliable - see Story 26.3's findings)."""
        deadline = time.time() + self._max_reenumerate_wait_seconds
        delay = 2.0
        while time.time() < deadline:
            for path in self._transport.scan_for_reconnect_candidates():
                if self._try_candidate(path):
                    return path
            time.sleep(delay)
            delay = min(delay * 2, 8.0)
        return None

    def _try_candidate(self, path: str) -> bool:
        """Connect to a candidate path and check whether it's genuinely
        our device via its real local_node_id - not just whether the path
        connects at all, since a stale path can appear in scan results
        before the device is functionally ready, and a machine can have
        more than one matching device connected.

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


def build_device_watchdog(
    transport: BaseTransport,
    on_recovery_attempt: Optional[Callable[[], None]] = None,
    on_recovered: Optional[Callable[[RecoveryOutcome], None]] = None,
    on_recovery_failed: Optional[Callable[[RecoveryOutcome], None]] = None,
) -> Tuple[DeviceWatchdog, Optional[BasePowerControl]]:
    """Build a DeviceWatchdog for the given (already-connected) transport,
    reading power-control config from .env - shared by any UI layer
    (CLI/GUI, Story 26.5/26.6) so the config-parsing + construction logic
    isn't duplicated; only the callback bodies (how to report progress)
    are UI-specific.

    Returns (watchdog, power_control) - power_control is also returned
    (rather than only living inside the watchdog) so the caller can log/
    display whether automatic recovery is actually enabled without
    reaching into the watchdog's internals.
    """
    from core.config_loader import (
        get_relay_channel,
        get_relay_serial_port,
        load_relay_serial_baud,
    )
    from transport.power_control import SerialRelayPowerControl

    power_control: Optional[BasePowerControl] = None
    relay_port = get_relay_serial_port()
    if relay_port:
        relay_baud, _ = load_relay_serial_baud()
        power_control = SerialRelayPowerControl(
            relay_port, get_relay_channel(), relay_baud
        )

    watchdog = DeviceWatchdog(
        transport,
        power_control,
        device_node_id=transport.local_node_id,
        on_recovery_attempt=on_recovery_attempt,
        on_recovered=on_recovered,
        on_recovery_failed=on_recovery_failed,
    )
    return watchdog, power_control
