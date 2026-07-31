"""Tests for core/device_watchdog.py — DeviceWatchdog (Story 26.4).

Uses Mock(spec=BaseTransport)/Mock(spec=BasePowerControl), matching
tests/test_server_receiver.py's existing convention. time.time()/time.sleep
are patched in the module under test so re-enumeration-wait tests run
without actually waiting.
"""
import unittest
from unittest.mock import Mock, patch

from core.device_watchdog import DeviceWatchdog, RecoveryOutcome
from core.meshtastic_utils import DeviceInfo
from transport.base import BaseTransport, TransportConnectionError
from transport.power_control import BasePowerControl, PowerControlError


def make_watchdog(**overrides):
    transport = overrides.pop("transport", None) or Mock(spec=BaseTransport)
    power_control = overrides.pop("power_control", Mock(spec=BasePowerControl))
    kwargs = dict(
        transport=transport,
        power_control=power_control,
        device_node_id="!aee5ab3c",
        max_consecutive_failures=3,
        heartbeat_interval_seconds=60.0,
        max_reenumerate_wait_seconds=60.0,
    )
    kwargs.update(overrides)
    return DeviceWatchdog(**kwargs), transport, power_control


class TestRecordSuccessFailure(unittest.TestCase):
    def test_record_failure_does_not_trip_before_threshold(self):
        watchdog, transport, power_control = make_watchdog(max_consecutive_failures=3)
        watchdog.record_failure()
        watchdog.record_failure()
        transport.disconnect.assert_not_called()
        power_control.power_cycle.assert_not_called()

    def test_record_failure_trips_recovery_at_threshold(self):
        on_recovery_attempt = Mock()
        watchdog, transport, power_control = make_watchdog(
            max_consecutive_failures=3, on_recovery_attempt=on_recovery_attempt
        )
        # Short-circuit at the power_cycle step - this test only cares that
        # recovery started, not about the full success/wait path.
        power_control.power_cycle.side_effect = PowerControlError("test")

        watchdog.record_failure()
        watchdog.record_failure()
        watchdog.record_failure()

        on_recovery_attempt.assert_called_once()
        transport.disconnect.assert_called_once()

    def test_record_success_resets_failure_counter(self):
        on_recovery_attempt = Mock()
        watchdog, transport, power_control = make_watchdog(
            max_consecutive_failures=3, on_recovery_attempt=on_recovery_attempt
        )
        watchdog.record_failure()
        watchdog.record_failure()
        watchdog.record_success()
        watchdog.record_failure()
        watchdog.record_failure()
        on_recovery_attempt.assert_not_called()


class TestTick(unittest.TestCase):
    def test_tick_skips_check_before_interval_elapsed(self):
        watchdog, transport, power_control = make_watchdog(heartbeat_interval_seconds=60.0)
        watchdog.tick(now=10.0)
        transport.check_alive.assert_not_called()

    def test_tick_checks_alive_once_interval_elapsed(self):
        watchdog, transport, power_control = make_watchdog(heartbeat_interval_seconds=60.0)
        transport.check_alive.return_value = True
        watchdog.tick(now=61.0)
        transport.check_alive.assert_called_once()

    def test_tick_trips_recovery_when_not_alive(self):
        on_recovery_attempt = Mock()
        watchdog, transport, power_control = make_watchdog(
            heartbeat_interval_seconds=60.0, on_recovery_attempt=on_recovery_attempt
        )
        transport.check_alive.return_value = False
        # Short-circuit at the power_cycle step - this test only cares that
        # recovery started, not about the full success/wait path.
        power_control.power_cycle.side_effect = PowerControlError("test")

        watchdog.tick(now=61.0)

        on_recovery_attempt.assert_called_once()
        transport.disconnect.assert_called_once()

    def test_tick_does_not_trip_recovery_when_alive(self):
        on_recovery_attempt = Mock()
        watchdog, transport, power_control = make_watchdog(
            heartbeat_interval_seconds=60.0, on_recovery_attempt=on_recovery_attempt
        )
        transport.check_alive.return_value = True
        watchdog.tick(now=61.0)
        on_recovery_attempt.assert_not_called()


class TestRecoveryNoPowerControl(unittest.TestCase):
    def test_fails_immediately_without_power_control(self):
        on_recovery_failed = Mock()
        watchdog, transport, _ = make_watchdog(
            power_control=None, on_recovery_failed=on_recovery_failed
        )
        watchdog.record_failure()
        watchdog.record_failure()
        watchdog.record_failure()

        on_recovery_failed.assert_called_once()
        outcome = on_recovery_failed.call_args[0][0]
        self.assertIsInstance(outcome, RecoveryOutcome)
        self.assertFalse(outcome.success)
        self.assertIn("No power control configured", outcome.error)


class TestRecoveryPowerCycleFailure(unittest.TestCase):
    def test_fails_when_power_cycle_raises(self):
        on_recovery_failed = Mock()
        watchdog, transport, power_control = make_watchdog(
            on_recovery_failed=on_recovery_failed
        )
        power_control.power_cycle.side_effect = PowerControlError("uhubctl not found")

        watchdog.record_failure()
        watchdog.record_failure()
        watchdog.record_failure()

        on_recovery_failed.assert_called_once()
        outcome = on_recovery_failed.call_args[0][0]
        self.assertFalse(outcome.success)
        self.assertIn("Power cycle failed", outcome.error)
        self.assertIn("uhubctl not found", outcome.error)


class TestRecoverySuccessPaths(unittest.TestCase):
    def test_recovers_via_matching_node_id(self):
        on_recovered = Mock()
        watchdog, transport, power_control = make_watchdog(
            device_node_id="!aee5ab3c", on_recovered=on_recovered
        )
        after = [DeviceInfo(path="/dev/ttyNEW", serial_number=None, description="x")]
        transport.local_node_id = "!aee5ab3c"

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=after
        ), patch("core.device_watchdog.time.time", side_effect=[100.0, 100.0]), patch(
            "core.device_watchdog.time.sleep"
        ):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        power_control.power_cycle.assert_called_once()
        transport.connect.assert_called_once_with("/dev/ttyNEW")
        transport.disconnect.assert_called_once()  # only the initial disconnect - no mismatch disconnect
        on_recovered.assert_called_once()
        outcome = on_recovered.call_args[0][0]
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.new_device_path, "/dev/ttyNEW")

    def test_recovers_via_any_connect_when_node_id_unknown(self):
        """device_node_id is None - only safe for the normal single-device
        deployment, but should still accept whatever connects."""
        on_recovered = Mock()
        watchdog, transport, power_control = make_watchdog(
            device_node_id=None, on_recovered=on_recovered
        )
        after = [DeviceInfo(path="/dev/ttyNEW", serial_number=None, description="x")]
        transport.local_node_id = "!whatever"

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=after
        ), patch("core.device_watchdog.time.time", side_effect=[100.0, 100.0]), patch(
            "core.device_watchdog.time.sleep"
        ):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        transport.connect.assert_called_once_with("/dev/ttyNEW")
        on_recovered.assert_called_once()
        self.assertTrue(on_recovered.call_args[0][0].success)


class TestRecoveryNodeIdMismatch(unittest.TestCase):
    def test_disconnects_and_tries_next_candidate_on_node_id_mismatch(self):
        """A machine can have more than one Meshtastic-like device - a
        candidate that connects but has the wrong node_id must be
        disconnected and rejected, not accepted as a match."""
        on_recovered = Mock()
        watchdog, transport, power_control = make_watchdog(
            device_node_id="!aee5ab3c", on_recovered=on_recovered
        )
        after = [
            DeviceInfo(path="/dev/ttyWRONG", serial_number=None, description="x"),
            DeviceInfo(path="/dev/ttyRIGHT", serial_number=None, description="x"),
        ]
        # First candidate connects but is the wrong device; second is ours.
        transport.local_node_id = "!wrongnode"

        def connect_side_effect(path):
            if path == "/dev/ttyRIGHT":
                transport.local_node_id = "!aee5ab3c"

        transport.connect.side_effect = connect_side_effect

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=after
        ), patch("core.device_watchdog.time.time", side_effect=[100.0, 100.0]), patch(
            "core.device_watchdog.time.sleep"
        ):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        self.assertEqual(
            transport.connect.call_args_list,
            [unittest.mock.call("/dev/ttyWRONG"), unittest.mock.call("/dev/ttyRIGHT")],
        )
        on_recovered.assert_called_once()
        self.assertEqual(on_recovered.call_args[0][0].new_device_path, "/dev/ttyRIGHT")


class TestRecoveryReenumerationTimeout(unittest.TestCase):
    def test_fails_when_device_never_reappears(self):
        on_recovery_failed = Mock()
        watchdog, transport, power_control = make_watchdog(
            on_recovery_failed=on_recovery_failed, max_reenumerate_wait_seconds=10.0
        )

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=[]
        ), patch(
            "core.device_watchdog.time.time", side_effect=[100.0, 100.0, 200.0]
        ), patch("core.device_watchdog.time.sleep"):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        on_recovery_failed.assert_called_once()
        outcome = on_recovery_failed.call_args[0][0]
        self.assertIn("did not reappear", outcome.error)


class TestRecoveryStalePathRejection(unittest.TestCase):
    def test_keeps_polling_when_connect_fails_before_succeeding(self):
        """A candidate path appearing in scan results doesn't mean the
        device is functionally ready yet - a failed connect attempt
        should be retried, not treated as a final failure."""
        on_recovered = Mock()
        watchdog, transport, power_control = make_watchdog(
            device_node_id="!aee5ab3c", on_recovered=on_recovered
        )
        after = [DeviceInfo(path="/dev/ttyNEW", serial_number=None, description="x")]
        transport.local_node_id = "!aee5ab3c"
        # First connect attempt fails (stale path not yet ready), second succeeds.
        transport.connect.side_effect = [
            TransportConnectionError("not ready yet"),
            None,
        ]

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=after
        ), patch(
            "core.device_watchdog.time.time", side_effect=[100.0, 100.0, 110.0]
        ), patch("core.device_watchdog.time.sleep"):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        on_recovered.assert_called_once()
        self.assertEqual(transport.connect.call_count, 2)


class TestRecoveryResetsFailureCounter(unittest.TestCase):
    def test_successful_recovery_resets_failure_counter(self):
        watchdog, transport, power_control = make_watchdog(
            device_node_id="!aee5ab3c", max_consecutive_failures=3
        )
        after = [DeviceInfo(path="/dev/ttyNEW", serial_number=None, description="x")]
        transport.local_node_id = "!aee5ab3c"

        with patch(
            "core.device_watchdog.scan_meshtastic_devices_detailed", return_value=after
        ), patch("core.device_watchdog.time.time", side_effect=[100.0, 100.0]), patch(
            "core.device_watchdog.time.sleep"
        ):
            watchdog.record_failure()
            watchdog.record_failure()
            watchdog.record_failure()

        # A single subsequent failure should not immediately re-trip
        # recovery, since the counter was reset by the successful recovery.
        power_control.power_cycle.reset_mock()
        watchdog.record_failure()
        power_control.power_cycle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
