"""Tests for transport/power_control.py.

Covers UhubctlPowerControl's subprocess invocation and error handling.
No real hardware/uhubctl binary needed - subprocess.run is mocked
throughout.
"""
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from transport.power_control import PowerControlError, UhubctlPowerControl


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


if __name__ == "__main__":
    unittest.main()
