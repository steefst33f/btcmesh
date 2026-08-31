"""Tests for transport/power_control.py.

Covers UhubctlPowerControl's subprocess invocation and error handling, and
SerialRelayPowerControl's serial protocol handling. No real hardware/uhubctl
binary/ESP32 needed - subprocess.run and serial.Serial are mocked throughout.
"""
import subprocess
import threading
import unittest
from unittest.mock import patch, MagicMock

import serial

from transport.power_control import (
    PowerControlError,
    UhubctlPowerControl,
    SerialRelayPowerControl,
    probe_relay_board_id,
)


class TestUhubctlPowerControlInvocation(unittest.TestCase):
    """Tests for the exact subprocess command UhubctlPowerControl builds."""

    def test_default_cycles_whole_hub_location_with_force(self):
        """No port specified - cycles the whole hub location. Always passes
        --force, since uhubctl refuses non-ppps (e.g. ganged) hubs otherwise -
        see Issue 12/16's real hardware, which reports as ganged."""
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            power_control = UhubctlPowerControl(location="2-1.4")

            power_control.power_cycle(off_seconds=15.0)

            mock_run.assert_called_once_with(
                ["uhubctl", "--force", "-l", "2-1.4", "-a", "cycle", "-d", "15.0"],
                capture_output=True, text=True, timeout=25.0,
            )

    def test_explicit_port_included_when_given(self):
        """Only meaningful on a genuinely ppps-capable hub - see the class
        docstring - but the option must still be passed through correctly."""
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            power_control = UhubctlPowerControl(location="1-2", port=3)

            power_control.power_cycle(off_seconds=10.0)

            mock_run.assert_called_once_with(
                ["uhubctl", "--force", "-l", "1-2", "-a", "cycle", "-d", "10.0", "-p", "3"],
                capture_output=True, text=True, timeout=20.0,
            )

    def test_default_off_seconds_is_15(self):
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            power_control = UhubctlPowerControl(location="2-1.4")

            power_control.power_cycle()

            args = mock_run.call_args.args[0]
            self.assertIn("15.0", args)


class TestUhubctlPowerControlErrorHandling(unittest.TestCase):
    """Tests for PowerControlError being raised on the various failure modes."""

    def test_nonzero_returncode_raises_with_stderr(self):
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="no permission")
            power_control = UhubctlPowerControl(location="2-1.4")

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("no permission", str(ctx.exception))

    def test_nonzero_returncode_falls_back_to_stdout_when_no_stderr(self):
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="hub not found", stderr="")
            power_control = UhubctlPowerControl(location="9-9")

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("hub not found", str(ctx.exception))

    def test_uhubctl_not_installed_raises_helpful_error(self):
        with patch("transport.power_control.subprocess.run", side_effect=FileNotFoundError()):
            power_control = UhubctlPowerControl(location="2-1.4")

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("uhubctl not found", str(ctx.exception))

    def test_timeout_raises_power_control_error(self):
        with patch(
            "transport.power_control.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="uhubctl", timeout=25.0),
        ):
            power_control = UhubctlPowerControl(location="2-1.4")

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle(off_seconds=15.0)
            self.assertIn("timed out", str(ctx.exception))

    def test_success_does_not_raise(self):
        with patch("transport.power_control.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            power_control = UhubctlPowerControl(location="2-1.4")

            power_control.power_cycle()  # must not raise


def _mock_serial(mock_serial_cls, response=b"OK\n"):
    """Configure a patched serial.Serial class to behave as a context
    manager yielding a mock port whose readline() returns `response`."""
    mock_port = MagicMock()
    mock_port.readline.return_value = response
    mock_serial_cls.return_value.__enter__.return_value = mock_port
    return mock_port


def _mock_serial_direct(mock_serial_cls, response=b"OK\n"):
    """Configure a patched serial.Serial class to return a mock port
    directly from the constructor (not via the context-manager protocol) -
    probe_relay_board_id() (Issue 57) constructs the port on a worker
    thread and uses it directly, rather than via `with serial.Serial(...)
    as ser:`."""
    mock_port = MagicMock()
    mock_port.readline.return_value = response
    mock_serial_cls.return_value = mock_port
    return mock_port


class TestSerialRelayPowerControlInvocation(unittest.TestCase):
    """Tests for the exact serial command SerialRelayPowerControl sends."""

    def test_sends_correct_cycle_command(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            mock_port = _mock_serial(mock_serial_cls)
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            power_control.power_cycle(off_seconds=15.0)

            mock_serial_cls.assert_called_once_with(
                "/dev/ttyUSB0", 115200, timeout=25.0
            )
            mock_port.write.assert_called_once_with(b"CYCLE 1 15\n")

    def test_different_channel_included_in_command(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            mock_port = _mock_serial(mock_serial_cls)
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=2)

            power_control.power_cycle(off_seconds=10.0)

            mock_port.write.assert_called_once_with(b"CYCLE 2 10\n")

    def test_custom_baudrate_is_used(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial(mock_serial_cls)
            power_control = SerialRelayPowerControl(
                port="/dev/ttyUSB0", channel=1, baudrate=9600
            )

            power_control.power_cycle()

            mock_serial_cls.assert_called_once_with(
                "/dev/ttyUSB0", 9600, timeout=25.0
            )

    def test_default_off_seconds_is_15(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            mock_port = _mock_serial(mock_serial_cls)
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            power_control.power_cycle()

            mock_port.write.assert_called_once_with(b"CYCLE 1 15\n")


class TestSerialRelayPowerControlErrorHandling(unittest.TestCase):
    """Tests for PowerControlError being raised on the various failure modes."""

    def test_ok_response_does_not_raise(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial(mock_serial_cls, response=b"OK\n")
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            power_control.power_cycle()  # must not raise

    def test_err_response_raises_with_reason(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial(mock_serial_cls, response=b"ERR invalid channel\n")
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("ERR invalid channel", str(ctx.exception))

    def test_empty_response_raises_timeout_error(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial(mock_serial_cls, response=b"")
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle(off_seconds=15.0)
            self.assertIn("did not respond", str(ctx.exception))

    def test_serial_exception_raises_power_control_error(self):
        with patch(
            "transport.power_control.serial.Serial",
            side_effect=serial.SerialException("port busy"),
        ):
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("port busy", str(ctx.exception))

    def test_oserror_raises_power_control_error(self):
        with patch(
            "transport.power_control.serial.Serial",
            side_effect=OSError("no such device"),
        ):
            power_control = SerialRelayPowerControl(port="/dev/ttyUSB0", channel=1)

            with self.assertRaises(PowerControlError) as ctx:
                power_control.power_cycle()
            self.assertIn("no such device", str(ctx.exception))


class TestProbeRelayBoardId(unittest.TestCase):
    """Tests for probe_relay_board_id() (Issue 37's false-positive-half
    fix) - a quick raw-serial check against the relay firmware's ID
    command. No legacy-firmware fallback needed - there's exactly one
    physical relay board for this project, always reflashed to current
    firmware alongside the host-side code that depends on it."""

    def test_id_response_returns_unique_id(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            mock_port = _mock_serial_direct(mock_serial_cls, response=b"BTCMESH-RELAY 246F28AECB34\n")

            result = probe_relay_board_id("/dev/ttyUSB0")

            self.assertEqual(result, "246F28AECB34")
            mock_port.write.assert_called_once_with(b"ID\n")

    def test_sends_id_command_not_a_cycle_command(self):
        """Must never send anything that could be mistaken for a real
        CYCLE command."""
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            mock_port = _mock_serial_direct(mock_serial_cls, response=b"BTCMESH-RELAY 246F28AECB34\n")

            probe_relay_board_id("/dev/ttyUSB0")

            sent = mock_port.write.call_args[0][0]
            self.assertNotIn(b"CYCLE", sent)

    def test_unrecognized_response_returns_none(self):
        """Covers both a real Meshtastic device's response (never this
        exact format - must never be misidentified as the relay board)
        and an "ERR unknown command" reply (e.g. from firmware without
        the ID command) - neither confirms this is the relay board."""
        for response in (b"\x94\xc3\x00\x02garbage", b"ERR unknown command\n"):
            with patch("transport.power_control.serial.Serial") as mock_serial_cls:
                _mock_serial_direct(mock_serial_cls, response=response)

                result = probe_relay_board_id("/dev/ttyUSB0")

                self.assertIsNone(result)

    def test_no_response_returns_none(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial_direct(mock_serial_cls, response=b"")

            result = probe_relay_board_id("/dev/ttyUSB0")

            self.assertIsNone(result)

    def test_serial_exception_returns_none_not_raise(self):
        with patch(
            "transport.power_control.serial.Serial",
            side_effect=serial.SerialException("port busy"),
        ):
            result = probe_relay_board_id("/dev/ttyUSB0")

            self.assertIsNone(result)

    def test_oserror_returns_none_not_raise(self):
        with patch(
            "transport.power_control.serial.Serial",
            side_effect=OSError("no such device"),
        ):
            result = probe_relay_board_id("/dev/ttyUSB0")

            self.assertIsNone(result)

    def test_custom_baudrate_and_timeout_are_used(self):
        with patch("transport.power_control.serial.Serial") as mock_serial_cls:
            _mock_serial_direct(mock_serial_cls, response=b"BTCMESH-RELAY 246F28AECB34\n")

            probe_relay_board_id("/dev/ttyUSB0", baudrate=9600, timeout=1.5)

            mock_serial_cls.assert_called_once_with("/dev/ttyUSB0", 9600, timeout=1.5)

    def test_open_blocking_forever_returns_none_not_hang(self):
        """Issue 57: serial.Serial()'s own port-open can block forever -
        the timeout= constructor arg only bounds the subsequent
        readline(), not the open itself. probe_relay_board_id() must give
        up and return None (its documented 'never raises' contract)
        rather than hanging indefinitely."""
        release_event = threading.Event()

        def blocking_open(*args, **kwargs):
            release_event.wait()  # never set - simulates an indefinite hang

        with patch(
            "transport.power_control.serial.Serial", side_effect=blocking_open
        ):
            with patch("transport.power_control._OPEN_TIMEOUT_SECONDS", 0.05):
                with self.assertLogs(
                    "transport.power_control", level="WARNING"
                ) as cm:
                    result = probe_relay_board_id("/dev/ttyUSB0")

        self.assertIsNone(result)
        self.assertTrue(any("did not return" in msg for msg in cm.output))

        release_event.set()  # let the abandoned worker thread finish, for cleanup


if __name__ == "__main__":
    unittest.main()
