"""Tests for transport/power_control.py.

Covers UhubctlPowerControl's subprocess invocation and error handling, and
SerialRelayPowerControl's serial protocol handling. No real hardware/uhubctl
binary/ESP32 needed - subprocess.run and serial.Serial are mocked throughout.
"""
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import serial

from transport.power_control import (
    PowerControlError,
    UhubctlPowerControl,
    SerialRelayPowerControl,
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


if __name__ == "__main__":
    unittest.main()
