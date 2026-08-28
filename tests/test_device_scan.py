#!/usr/bin/env python3
"""
Tests for BTCMesh's shared device-scanning module (core/device_scan.py).

Moved here from tests/test_meshtastic_utils.py (Story 30.4 cleanup):
candidate-port enumeration has nothing transport-specific about it, so
it's tested once here rather than duplicated per transport.
"""
import sys
import unittest
import unittest.mock


class TestScanSerialDevices(unittest.TestCase):
    """Tests for scan_serial_devices()."""

    def test_scan_serial_devices_exists(self):
        """Given core.device_scan, Then scan_serial_devices should be defined."""
        from core.device_scan import scan_serial_devices
        self.assertTrue(callable(scan_serial_devices))

    def test_scan_returns_list(self):
        """Given scan_serial_devices call, Then it returns a list."""
        from core.device_scan import scan_serial_devices
        result = scan_serial_devices()
        self.assertIsInstance(result, list)

    def test_scan_returns_empty_when_meshtastic_not_installed(self):
        """Given meshtastic not installed, Then returns empty list."""
        from core.device_scan import scan_serial_devices

        with unittest.mock.patch.dict(sys.modules, {'meshtastic': None, 'meshtastic.util': None}):
            # Force reimport
            import importlib
            import core.device_scan
            importlib.reload(core.device_scan)
            result = core.device_scan.scan_serial_devices()
            self.assertEqual(result, [])

    def test_scan_returns_ports_when_found(self):
        """Given non-blacklisted serial ports, Then returns those ports.

        Uses the real meshtastic.util.blacklistVids/eliminate_duplicate_port —
        only the hardware enumeration (comports) is mocked, since we can't
        depend on real USB devices being attached in CI.
        """
        from core import device_scan

        mock_ports = [
            unittest.mock.MagicMock(device='/dev/ttyUSB0', vid=0x303a),
            unittest.mock.MagicMock(device='/dev/ttyACM0', vid=0x2886),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = device_scan.scan_serial_devices()
            self.assertEqual(result, ['/dev/ttyACM0', '/dev/ttyUSB0'])

    def test_scan_includes_non_whitelisted_vid_alongside_whitelisted(self):
        """Given one Espressif-VID device (0x303a, whitelisted by
        meshtastic.util.findPorts) and one Seeed-VID device (0x2886, not
        whitelisted there) connected together, Then both are returned.

        Regression test: meshtastic.util.findPorts() only falls back to
        "not blacklisted" ports when zero whitelisted-VID ports are found, so
        it silently drops the second device entirely in this scenario. Uses
        the real meshtastic.util.blacklistVids/eliminate_duplicate_port to
        prove the fix holds against the actual upstream library.
        """
        from core import device_scan

        mock_ports = [
            unittest.mock.MagicMock(device='/dev/cu.usbmodemESP32', vid=0x303a),
            unittest.mock.MagicMock(device='/dev/cu.usbmodemSeeed', vid=0x2886),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = device_scan.scan_serial_devices()
            self.assertEqual(
                result, ['/dev/cu.usbmodemESP32', '/dev/cu.usbmodemSeeed']
            )


class TestScanSerialDevicesDetailed(unittest.TestCase):
    """Tests for scan_serial_devices_detailed() (Story 26.3)."""

    def test_scan_serial_devices_detailed_exists(self):
        from core.device_scan import scan_serial_devices_detailed
        self.assertTrue(callable(scan_serial_devices_detailed))

    def test_scan_returns_list(self):
        from core.device_scan import scan_serial_devices_detailed
        result = scan_serial_devices_detailed()
        self.assertIsInstance(result, list)

    def test_scan_returns_empty_when_meshtastic_not_installed(self):
        from core.device_scan import scan_serial_devices_detailed

        with unittest.mock.patch.dict(sys.modules, {'meshtastic': None, 'meshtastic.util': None}):
            import importlib
            import core.device_scan
            importlib.reload(core.device_scan)
            result = core.device_scan.scan_serial_devices_detailed()
            self.assertEqual(result, [])

    def test_scan_returns_device_info_with_serial_and_description(self):
        """Given non-blacklisted serial ports, Then returns DeviceInfo
        entries carrying path, serial_number, and description."""
        from core import device_scan

        mock_ports = [
            unittest.mock.MagicMock(
                device='/dev/ttyUSB0', vid=0x303a,
                serial_number='ABC123', description='Some ESP32 board',
            ),
            unittest.mock.MagicMock(
                device='/dev/ttyACM0', vid=0x2886,
                serial_number=None, description='Some Seeed board',
            ),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = device_scan.scan_serial_devices_detailed()

            self.assertEqual([d.path for d in result], ['/dev/ttyACM0', '/dev/ttyUSB0'])
            by_path = {d.path: d for d in result}
            self.assertEqual(by_path['/dev/ttyUSB0'].serial_number, 'ABC123')
            self.assertEqual(by_path['/dev/ttyUSB0'].description, 'Some ESP32 board')
            self.assertIsNone(by_path['/dev/ttyACM0'].serial_number)

    def test_scan_includes_non_whitelisted_vid_alongside_whitelisted(self):
        """Same VID-blacklist regression as scan_serial_devices, applied
        to the detailed variant."""
        from core import device_scan

        mock_ports = [
            unittest.mock.MagicMock(
                device='/dev/cu.usbmodemESP32', vid=0x303a,
                serial_number='S1', description='ESP32',
            ),
            unittest.mock.MagicMock(
                device='/dev/cu.usbmodemSeeed', vid=0x2886,
                serial_number='S2', description='Seeed',
            ),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = device_scan.scan_serial_devices_detailed()
            self.assertEqual(
                [d.path for d in result],
                ['/dev/cu.usbmodemESP32', '/dev/cu.usbmodemSeeed'],
            )

    def test_scan_deduplicates_same_physical_device(self):
        """Given two OS-level names for the same physical device (a known
        macOS quirk - see meshtastic.util.eliminate_duplicate_port), Then
        only the winning DeviceInfo entry is returned, matching the exact
        same dedup behavior as scan_serial_devices()."""
        from core import device_scan

        mock_ports = [
            unittest.mock.MagicMock(
                device='/dev/cu.usbserial-1430', vid=0x10c4,
                serial_number='1430', description='CP2102',
            ),
            unittest.mock.MagicMock(
                device='/dev/cu.wchusbserial1430', vid=0x10c4,
                serial_number='1430', description='CP2102',
            ),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = device_scan.scan_serial_devices_detailed()
            self.assertEqual([d.path for d in result], ['/dev/cu.wchusbserial1430'])

    def test_scan_returns_empty_on_generic_exception(self):
        from core import device_scan

        with unittest.mock.patch(
            'serial.tools.list_ports.comports', side_effect=RuntimeError("boom")
        ):
            result = device_scan.scan_serial_devices_detailed()
            self.assertEqual(result, [])


class TestFormatDeviceDisplay(unittest.TestCase):
    """Tests for format_device_display() (Story 27.1)."""

    def test_format_device_display_exists(self):
        from core.device_scan import format_device_display
        self.assertTrue(callable(format_device_display))

    def test_path_only_when_node_id_none(self):
        from core.device_scan import format_device_display

        result = format_device_display('/dev/cu.usbserial-0001', None)
        self.assertEqual(result, '/dev/cu.usbserial-0001')

    def test_path_and_node_id_when_known(self):
        from core.device_scan import format_device_display

        result = format_device_display('/dev/cu.usbserial-0001', '!7c5b4418')
        self.assertEqual(result, '/dev/cu.usbserial-0001 (!7c5b4418)')

    def test_name_and_node_id_when_both_known(self):
        """Given both a node_id and a name, Then the name is shown instead
        of the raw path - e.g. 'Meshtastic 4418 (!7c5b4418)'."""
        from core.device_scan import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', '!7c5b4418', name='Meshtastic 4418'
        )
        self.assertEqual(result, 'Meshtastic 4418 (!7c5b4418)')

    def test_path_and_node_id_when_name_is_none(self):
        """Given a node_id but no name (device has none configured), Then
        falls back to path (node_id) rather than showing nothing."""
        from core.device_scan import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', '!7c5b4418', name=None
        )
        self.assertEqual(result, '/dev/cu.usbserial-0001 (!7c5b4418)')

    def test_name_only_when_node_id_none(self):
        """Given a name but no node_id, Then shows the name alone rather
        than falling back to the bare path. This is a real, meaningful
        case (not just an edge case to tolerate): probe_device_identity()'s
        Issue 37 relay-board result has a descriptive name
        ('Relay board (not a Meshtastic device)') but no Meshtastic
        protocol identity to pair it with."""
        from core.device_scan import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', None, name='Relay board (not a Meshtastic device)'
        )
        self.assertEqual(result, 'Relay board (not a Meshtastic device)')


if __name__ == '__main__':
    unittest.main()
