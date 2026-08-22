#!/usr/bin/env python3
"""
Tests for BTCMesh Meshtastic Utilities (core/meshtastic_utils.py).

Tests device scanning, node information retrieval, and formatting functions.
"""
import sys
import unittest
import unittest.mock
import time


class TestScanMeshtasticDevices(unittest.TestCase):
    """Tests for scan_meshtastic_devices function."""

    def test_scan_meshtastic_devices_exists(self):
        """Given meshtastic_utils module, Then scan_meshtastic_devices should be defined."""
        from core.meshtastic_utils import scan_meshtastic_devices
        self.assertTrue(callable(scan_meshtastic_devices))

    def test_scan_returns_list(self):
        """Given scan_meshtastic_devices call, Then it returns a list."""
        from core.meshtastic_utils import scan_meshtastic_devices
        result = scan_meshtastic_devices()
        self.assertIsInstance(result, list)

    def test_scan_returns_empty_when_meshtastic_not_installed(self):
        """Given meshtastic not installed, Then returns empty list."""
        from core.meshtastic_utils import scan_meshtastic_devices

        with unittest.mock.patch.dict(sys.modules, {'meshtastic': None, 'meshtastic.util': None}):
            # Force reimport
            import importlib
            import core.meshtastic_utils
            importlib.reload(core.meshtastic_utils)
            result = core.meshtastic_utils.scan_meshtastic_devices()
            self.assertEqual(result, [])

    def test_scan_returns_ports_when_found(self):
        """Given non-blacklisted serial ports, Then returns those ports.

        Uses the real meshtastic.util.blacklistVids/eliminate_duplicate_port —
        only the hardware enumeration (comports) is mocked, since we can't
        depend on real USB devices being attached in CI.
        """
        from core import meshtastic_utils

        mock_ports = [
            unittest.mock.MagicMock(device='/dev/ttyUSB0', vid=0x303a),
            unittest.mock.MagicMock(device='/dev/ttyACM0', vid=0x2886),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = meshtastic_utils.scan_meshtastic_devices()
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
        from core import meshtastic_utils

        mock_ports = [
            unittest.mock.MagicMock(device='/dev/cu.usbmodemESP32', vid=0x303a),
            unittest.mock.MagicMock(device='/dev/cu.usbmodemSeeed', vid=0x2886),
        ]

        with unittest.mock.patch('serial.tools.list_ports.comports', return_value=mock_ports):
            result = meshtastic_utils.scan_meshtastic_devices()
            self.assertEqual(
                result, ['/dev/cu.usbmodemESP32', '/dev/cu.usbmodemSeeed']
            )


class TestScanMeshtasticDevicesDetailed(unittest.TestCase):
    """Tests for scan_meshtastic_devices_detailed (Story 26.3)."""

    def test_scan_meshtastic_devices_detailed_exists(self):
        from core.meshtastic_utils import scan_meshtastic_devices_detailed
        self.assertTrue(callable(scan_meshtastic_devices_detailed))

    def test_scan_returns_list(self):
        from core.meshtastic_utils import scan_meshtastic_devices_detailed
        result = scan_meshtastic_devices_detailed()
        self.assertIsInstance(result, list)

    def test_scan_returns_empty_when_meshtastic_not_installed(self):
        from core.meshtastic_utils import scan_meshtastic_devices_detailed

        with unittest.mock.patch.dict(sys.modules, {'meshtastic': None, 'meshtastic.util': None}):
            import importlib
            import core.meshtastic_utils
            importlib.reload(core.meshtastic_utils)
            result = core.meshtastic_utils.scan_meshtastic_devices_detailed()
            self.assertEqual(result, [])

    def test_scan_returns_device_info_with_serial_and_description(self):
        """Given non-blacklisted serial ports, Then returns DeviceInfo
        entries carrying path, serial_number, and description."""
        from core import meshtastic_utils

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
            result = meshtastic_utils.scan_meshtastic_devices_detailed()

            self.assertEqual([d.path for d in result], ['/dev/ttyACM0', '/dev/ttyUSB0'])
            by_path = {d.path: d for d in result}
            self.assertEqual(by_path['/dev/ttyUSB0'].serial_number, 'ABC123')
            self.assertEqual(by_path['/dev/ttyUSB0'].description, 'Some ESP32 board')
            self.assertIsNone(by_path['/dev/ttyACM0'].serial_number)

    def test_scan_includes_non_whitelisted_vid_alongside_whitelisted(self):
        """Same VID-blacklist regression as scan_meshtastic_devices, applied
        to the detailed variant."""
        from core import meshtastic_utils

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
            result = meshtastic_utils.scan_meshtastic_devices_detailed()
            self.assertEqual(
                [d.path for d in result],
                ['/dev/cu.usbmodemESP32', '/dev/cu.usbmodemSeeed'],
            )

    def test_scan_deduplicates_same_physical_device(self):
        """Given two OS-level names for the same physical device (a known
        macOS quirk - see meshtastic.util.eliminate_duplicate_port), Then
        only the winning DeviceInfo entry is returned, matching the exact
        same dedup behavior as scan_meshtastic_devices()."""
        from core import meshtastic_utils

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
            result = meshtastic_utils.scan_meshtastic_devices_detailed()
            self.assertEqual([d.path for d in result], ['/dev/cu.wchusbserial1430'])

    def test_scan_returns_empty_on_generic_exception(self):
        from core import meshtastic_utils

        with unittest.mock.patch(
            'serial.tools.list_ports.comports', side_effect=RuntimeError("boom")
        ):
            result = meshtastic_utils.scan_meshtastic_devices_detailed()
            self.assertEqual(result, [])


class TestProbeDeviceIdentity(unittest.TestCase):
    """Tests for probe_device_identity (Story 27.1, extended to also
    fetch the node's configured name - see Issue 37 in
    project/issues.txt)."""

    def test_probe_device_identity_exists(self):
        from core.meshtastic_utils import probe_device_identity
        self.assertTrue(callable(probe_device_identity))

    def test_returns_node_id_and_name_on_successful_connect(self):
        """Given a transport that connects successfully, Then returns a
        ProbedDevice with both node_id and name, and disconnects
        afterward."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'core.meshtastic_utils.get_own_node_name', return_value='Meshtastic 4418'
        ) as mock_get_name:
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, '!7c5b4418')
        self.assertEqual(result.name, 'Meshtastic 4418')
        mock_transport.connect.assert_called_once_with('/dev/cu.usbserial-0001')
        mock_transport.disconnect.assert_called_once()
        mock_get_name.assert_called_once_with(mock_transport._iface)

    def test_returns_node_id_with_no_name_when_device_has_none_set(self):
        """Given a device with no configured name (get_own_node_name
        returns None), Then the ProbedDevice still carries the node_id."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'core.meshtastic_utils.get_own_node_name', return_value=None
        ):
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, '!7c5b4418')
        self.assertIsNone(result.name)

    def test_returns_empty_identity_when_connect_fails(self):
        """Given connect() raises TransportConnectionError (e.g. not a real
        Meshtastic device, already in use, or timed out), Then returns
        ProbedDevice(None, None) without raising, and still disconnects
        (safe no-op)."""
        from transport.base import TransportConnectionError

        mock_transport = unittest.mock.MagicMock()
        mock_transport.connect.side_effect = TransportConnectionError("No Meshtastic device found")

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ):
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-relay')

        self.assertIsNone(result.node_id)
        self.assertIsNone(result.name)
        mock_transport.disconnect.assert_called_once()


class TestFormatDeviceDisplay(unittest.TestCase):
    """Tests for format_device_display (Story 27.1)."""

    def test_format_device_display_exists(self):
        from core.meshtastic_utils import format_device_display
        self.assertTrue(callable(format_device_display))

    def test_path_only_when_node_id_none(self):
        from core.meshtastic_utils import format_device_display

        result = format_device_display('/dev/cu.usbserial-0001', None)
        self.assertEqual(result, '/dev/cu.usbserial-0001')

    def test_path_and_node_id_when_known(self):
        from core.meshtastic_utils import format_device_display

        result = format_device_display('/dev/cu.usbserial-0001', '!7c5b4418')
        self.assertEqual(result, '/dev/cu.usbserial-0001 (!7c5b4418)')

    def test_name_and_node_id_when_both_known(self):
        """Given both a node_id and a name, Then the name is shown instead
        of the raw path - e.g. 'Meshtastic 4418 (!7c5b4418)'."""
        from core.meshtastic_utils import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', '!7c5b4418', name='Meshtastic 4418'
        )
        self.assertEqual(result, 'Meshtastic 4418 (!7c5b4418)')

    def test_path_and_node_id_when_name_is_none(self):
        """Given a node_id but no name (device has none configured), Then
        falls back to path (node_id) rather than showing nothing."""
        from core.meshtastic_utils import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', '!7c5b4418', name=None
        )
        self.assertEqual(result, '/dev/cu.usbserial-0001 (!7c5b4418)')

    def test_path_only_when_name_known_but_node_id_none(self):
        """Given a name but no node_id (shouldn't normally happen - name
        only comes from a successful probe, which always yields a
        node_id too - but must not crash), Then still falls back to the
        bare path, since 'name' alone without a node_id would look like a
        wire-format node ID mismatch."""
        from core.meshtastic_utils import format_device_display

        result = format_device_display(
            '/dev/cu.usbserial-0001', None, name='Meshtastic 4418'
        )
        self.assertEqual(result, '/dev/cu.usbserial-0001')


class TestGetOwnNodeId(unittest.TestCase):
    """Tests for get_own_node_id function."""

    def test_get_own_node_id_exists(self):
        """Given meshtastic_utils module, Then get_own_node_id should be defined."""
        from core.meshtastic_utils import get_own_node_id
        self.assertTrue(callable(get_own_node_id))

    def test_returns_none_for_none_iface(self):
        """Given None interface, Then returns None."""
        from core.meshtastic_utils import get_own_node_id
        result = get_own_node_id(None)
        self.assertIsNone(result)

    def test_returns_none_when_no_myinfo(self):
        """Given interface with no myInfo, Then returns None."""
        from core.meshtastic_utils import get_own_node_id

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None

        result = get_own_node_id(mock_iface)
        self.assertIsNone(result)

    def test_returns_formatted_node_id(self):
        """Given valid interface, Then returns formatted node ID."""
        from core.meshtastic_utils import get_own_node_id

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234

        result = get_own_node_id(mock_iface)
        self.assertEqual(result, '!abcd1234')

    def test_returns_zero_padded_node_id(self):
        """Given small node number, Then returns zero-padded 8-char hex."""
        from core.meshtastic_utils import get_own_node_id

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0x1234

        result = get_own_node_id(mock_iface)
        self.assertEqual(result, '!00001234')


class TestGetOwnNodeName(unittest.TestCase):
    """Tests for get_own_node_name function."""

    def test_get_own_node_name_exists(self):
        """Given meshtastic_utils module, Then get_own_node_name should be defined."""
        from core.meshtastic_utils import get_own_node_name
        self.assertTrue(callable(get_own_node_name))

    def test_returns_none_for_none_iface(self):
        """Given None interface, Then returns None."""
        from core.meshtastic_utils import get_own_node_name
        result = get_own_node_name(None)
        self.assertIsNone(result)

    def test_returns_none_when_no_myinfo(self):
        """Given interface with no myInfo, Then returns None."""
        from core.meshtastic_utils import get_own_node_name

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None

        result = get_own_node_name(mock_iface)
        self.assertIsNone(result)

    def test_returns_long_name(self):
        """Given node with longName, Then returns longName."""
        from core.meshtastic_utils import get_own_node_name

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'longName': 'My Device',
                    'shortName': 'MD'
                }
            }
        }

        result = get_own_node_name(mock_iface)
        self.assertEqual(result, 'My Device')

    def test_returns_short_name_as_fallback(self):
        """Given node with only shortName, Then returns shortName."""
        from core.meshtastic_utils import get_own_node_name

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'longName': '',
                    'shortName': 'MD'
                }
            }
        }

        result = get_own_node_name(mock_iface)
        self.assertEqual(result, 'MD')

    def test_returns_none_when_no_name(self):
        """Given node with no name, Then returns None."""
        from core.meshtastic_utils import get_own_node_name

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'longName': '',
                    'shortName': ''
                }
            }
        }

        result = get_own_node_name(mock_iface)
        self.assertIsNone(result)


class TestGetKnownNodes(unittest.TestCase):
    """Tests for get_known_nodes function."""

    def test_get_known_nodes_exists(self):
        """Given meshtastic_utils module, Then get_known_nodes should be defined."""
        from core.meshtastic_utils import get_known_nodes
        self.assertTrue(callable(get_known_nodes))

    def test_returns_empty_for_none_iface(self):
        """Given None interface, Then returns empty list."""
        from core.meshtastic_utils import get_known_nodes
        result = get_known_nodes(None)
        self.assertEqual(result, [])

    def test_returns_empty_when_no_nodes(self):
        """Given interface with no nodes, Then returns empty list."""
        from core.meshtastic_utils import get_known_nodes

        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = None

        result = get_known_nodes(mock_iface)
        self.assertEqual(result, [])

    def test_excludes_own_node_by_default(self):
        """Given nodes including own, Then excludes own node."""
        from core.meshtastic_utils import get_known_nodes

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234
        mock_iface.nodes = {
            '!abcd1234': {'user': {'longName': 'Own Node'}},
            '!11111111': {'user': {'longName': 'Other Node'}},
        }

        result = get_known_nodes(mock_iface)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!11111111')

    def test_includes_own_node_when_exclude_false(self):
        """Given exclude_own=False, Then includes own node."""
        from core.meshtastic_utils import get_known_nodes

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xABCD1234
        mock_iface.nodes = {
            '!abcd1234': {'user': {'longName': 'Own Node'}},
            '!11111111': {'user': {'longName': 'Other Node'}},
        }

        result = get_known_nodes(mock_iface, exclude_own=False)
        self.assertEqual(len(result), 2)

    def test_sorts_by_last_heard_descending(self):
        """Given nodes with different lastHeard, Then sorts descending."""
        from core.meshtastic_utils import get_known_nodes

        now = int(time.time())
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None
        mock_iface.nodes = {
            '!11111111': {'user': {'longName': 'Old Node'}, 'lastHeard': now - 1000},
            '!22222222': {'user': {'longName': 'New Node'}, 'lastHeard': now - 10},
            '!33333333': {'user': {'longName': 'Middle Node'}, 'lastHeard': now - 500},
        }

        result = get_known_nodes(mock_iface)
        self.assertEqual(result[0]['id'], '!22222222')  # Most recent
        self.assertEqual(result[1]['id'], '!33333333')  # Middle
        self.assertEqual(result[2]['id'], '!11111111')  # Oldest

    def test_sorts_without_crashing_when_lastheard_is_none(self):
        """Given a node with lastHeard explicitly None (known but never
        actually heard from) alongside nodes with real timestamps, Then
        sorting doesn't crash and the None-lastHeard node sorts last.

        Regression test: node_data.get('lastHeard', 0) only applies the
        default when the key is missing, not when it's present but None,
        so the sort comparison used to raise TypeError comparing None to int.
        """
        from core.meshtastic_utils import get_known_nodes

        now = int(time.time())
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None
        mock_iface.nodes = {
            '!11111111': {'user': {'longName': 'Heard Node'}, 'lastHeard': now - 10},
            '!22222222': {'user': {'longName': 'Never Heard Node'}, 'lastHeard': None},
        }

        result = get_known_nodes(mock_iface)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], '!11111111')
        self.assertEqual(result[1]['id'], '!22222222')
        self.assertEqual(result[0]['lastHeard'], now - 10)
        self.assertEqual(result[1]['lastHeard'], 0)
        self.assertFalse(result[1]['is_recent'])

    def test_returns_node_info(self):
        """Given nodes, Then returns node info dict."""
        from core.meshtastic_utils import get_known_nodes

        now = int(time.time())
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None
        mock_iface.nodes = {
            '!11111111': {
                'user': {'longName': 'Test Node', 'shortName': 'TN'},
                'lastHeard': now - 100
            },
        }

        result = get_known_nodes(mock_iface)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!11111111')
        self.assertEqual(result[0]['name'], 'Test Node')
        self.assertEqual(result[0]['lastHeard'], now - 100)
        self.assertTrue(result[0]['is_recent'])  # Within 24 hours

    def test_is_recent_false_for_old_nodes(self):
        """Given node not heard in 24+ hours, Then is_recent is False."""
        from core.meshtastic_utils import get_known_nodes

        now = int(time.time())
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo = None
        mock_iface.nodes = {
            '!11111111': {
                'user': {'longName': 'Old Node'},
                'lastHeard': now - (25 * 60 * 60)  # 25 hours ago
            },
        }

        result = get_known_nodes(mock_iface)
        self.assertFalse(result[0]['is_recent'])


class TestFormatNodeDisplay(unittest.TestCase):
    """Tests for format_node_display function."""

    def test_format_node_display_exists(self):
        """Given meshtastic_utils module, Then format_node_display should be defined."""
        from core.meshtastic_utils import format_node_display
        self.assertTrue(callable(format_node_display))

    def test_formats_correctly(self):
        """Given node dict, Then returns 'Name (!nodeid)'."""
        from core.meshtastic_utils import format_node_display

        node = {'id': '!abcd1234', 'name': 'TestNode', 'lastHeard': 0, 'is_recent': False}
        result = format_node_display(node)
        self.assertEqual(result, 'TestNode (!abcd1234)')

    def test_handles_spaces_in_name(self):
        """Given node with spaces in name, Then formats correctly."""
        from core.meshtastic_utils import format_node_display

        node = {'id': '!12345678', 'name': 'My Test Node', 'lastHeard': 0, 'is_recent': False}
        result = format_node_display(node)
        self.assertEqual(result, 'My Test Node (!12345678)')


class TestGetNodeById(unittest.TestCase):
    """Tests for get_node_by_id function."""

    def test_get_node_by_id_exists(self):
        """Given meshtastic_utils module, Then get_node_by_id should be defined."""
        from core.meshtastic_utils import get_node_by_id
        self.assertTrue(callable(get_node_by_id))

    def test_returns_none_for_none_iface(self):
        """Given None interface, Then returns None."""
        from core.meshtastic_utils import get_node_by_id
        result = get_node_by_id(None, '!abcd1234')
        self.assertIsNone(result)

    def test_returns_none_when_node_not_found(self):
        """Given node ID not in nodes, Then returns None."""
        from core.meshtastic_utils import get_node_by_id

        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = {'!11111111': {'user': {'longName': 'Other'}}}

        result = get_node_by_id(mock_iface, '!abcd1234')
        self.assertIsNone(result)

    def test_returns_node_info(self):
        """Given valid node ID, Then returns node info dict."""
        from core.meshtastic_utils import get_node_by_id

        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {'longName': 'Test Node', 'shortName': 'TN'},
                'lastHeard': 12345
            }
        }

        result = get_node_by_id(mock_iface, '!abcd1234')
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], '!abcd1234')
        self.assertEqual(result['name'], 'Test Node')
        self.assertEqual(result['longName'], 'Test Node')
        self.assertEqual(result['shortName'], 'TN')
        self.assertEqual(result['lastHeard'], 12345)


if __name__ == '__main__':
    unittest.main()
