#!/usr/bin/env python3
"""
Tests for BTCMesh Meshtastic Utilities (core/meshtastic_utils.py).

Tests Meshtastic-specific identity probing, node information retrieval,
and formatting functions. Candidate-port enumeration is transport-
agnostic and tested once in tests/test_device_scan.py instead (Story
30.4 cleanup - core/meshtastic_utils.py no longer wraps it).
"""
import unittest
import unittest.mock
import time


class TestProbedDevice(unittest.TestCase):
    """Tests for the ProbedDevice dataclass (Story 27.4's firmware fields)."""

    def test_firmware_fields_default_none(self):
        """Given only node_id/name are passed, Then firmware_version and
        hw_model default to None - existing callers that construct
        ProbedDevice without them keep working unchanged."""
        from core.meshtastic_utils import ProbedDevice

        result = ProbedDevice(node_id=None, name=None)
        self.assertIsNone(result.firmware_version)
        self.assertIsNone(result.hw_model)


class TestProbeDeviceIdentity(unittest.TestCase):
    """Tests for probe_device_identity (Story 27.1, extended to also
    fetch the node's configured name - see Issue 37 in
    project/issues.txt)."""

    def test_probe_device_identity_exists(self):
        from core.meshtastic_utils import probe_device_identity
        self.assertTrue(callable(probe_device_identity))

    def test_returns_node_id_and_name_on_successful_connect(self):
        """Given a transport that connects successfully, Then returns a
        ProbedDevice with node_id, name, firmware_version, and hw_model,
        and disconnects afterward."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ), unittest.mock.patch(
            'core.meshtastic_utils.get_own_node_name', return_value='Meshtastic 4418'
        ) as mock_get_name, unittest.mock.patch(
            'core.meshtastic_utils.extract_firmware_info',
            return_value=('2.6.11.60ec05e', 'HELTEC_V3'),
        ):
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, '!7c5b4418')
        self.assertEqual(result.name, 'Meshtastic 4418')
        self.assertEqual(result.firmware_version, '2.6.11.60ec05e')
        self.assertEqual(result.hw_model, 'HELTEC_V3')
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
            'transport.power_control.probe_relay_board_id', return_value=None
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
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ):
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-relay')

        self.assertIsNone(result.node_id)
        self.assertIsNone(result.name)
        mock_transport.disconnect.assert_called_once()

    def test_returns_relay_board_identity_without_attempting_meshtastic_connect(self):
        """Issue 37 follow-up: given the candidate is confirmed to be the
        Story 26.7 relay board (its firmware reports a real
        hardware-derived unique ID), Then probe_device_identity() returns
        immediately with node_id set to that ID (prefixed '#', never
        confused with a real Meshtastic '!' node ID) - WITHOUT ever
        attempting the slow Meshtastic connect. Carrying a real node_id
        lets this piggyback on the existing dedupe_devices_by_node_id()
        mechanism, correctly collapsing one board's two OS-level aliases
        while keeping two *different* physical relay boards distinct."""
        from core.meshtastic_utils import RELAY_BOARD_NAME

        mock_transport = unittest.mock.MagicMock()

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value='246F28AECB34'
        ) as mock_probe_relay:
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-112440')

        mock_probe_relay.assert_called_once_with('/dev/cu.usbserial-112440')
        self.assertEqual(result.node_id, '#246F28AECB34')
        self.assertEqual(result.name, RELAY_BOARD_NAME)
        mock_transport.connect.assert_not_called()

    def test_extracts_firmware_and_hw_model_from_metadata(self):
        """Story 27.4: given the connected iface exposes metadata
        (populated for free by the connect handshake's waitForConfig()),
        Then firmware_version and hw_model are included on the
        ProbedDevice."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'
        mock_transport._iface.metadata.firmware_version = '2.6.11.60ec05e'
        mock_transport._iface.metadata.hw_model = 47

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ), unittest.mock.patch(
            'core.meshtastic_utils.get_own_node_name', return_value='Meshtastic 4418'
        ), unittest.mock.patch(
            'meshtastic.mesh_pb2.HardwareModel.Name', return_value='HELTEC_V3'
        ) as mock_name:
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.firmware_version, '2.6.11.60ec05e')
        self.assertEqual(result.hw_model, 'HELTEC_V3')
        mock_name.assert_called_once_with(47)

    def test_tolerates_missing_metadata(self):
        """Given the connected iface has no metadata (older firmware, or
        an unexpected shape), Then probe still succeeds with
        firmware_version/hw_model left None rather than raising."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'
        mock_transport._iface.metadata = None

        with unittest.mock.patch(
            'transport.meshtastic_serial.MeshtasticSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ), unittest.mock.patch(
            'core.meshtastic_utils.get_own_node_name', return_value='Meshtastic 4418'
        ):
            from core.meshtastic_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, '!7c5b4418')
        self.assertIsNone(result.firmware_version)
        self.assertIsNone(result.hw_model)


class TestExtractFirmwareInfo(unittest.TestCase):
    """Tests for extract_firmware_info (Story 27.4)."""

    def test_extract_firmware_info_exists(self):
        from core.meshtastic_utils import extract_firmware_info
        self.assertTrue(callable(extract_firmware_info))

    def test_extracts_from_metadata(self):
        from core.meshtastic_utils import extract_firmware_info

        iface = unittest.mock.MagicMock()
        iface.metadata.firmware_version = '2.6.11.60ec05e'
        iface.metadata.hw_model = 47

        with unittest.mock.patch(
            'meshtastic.mesh_pb2.HardwareModel.Name', return_value='HELTEC_V3'
        ) as mock_name:
            firmware_version, hw_model = extract_firmware_info(iface)

        self.assertEqual(firmware_version, '2.6.11.60ec05e')
        self.assertEqual(hw_model, 'HELTEC_V3')
        mock_name.assert_called_once_with(47)

    def test_returns_none_none_when_metadata_is_none(self):
        from core.meshtastic_utils import extract_firmware_info

        iface = unittest.mock.MagicMock()
        iface.metadata = None

        self.assertEqual(extract_firmware_info(iface), (None, None))

    def test_returns_none_none_when_iface_is_none(self):
        from core.meshtastic_utils import extract_firmware_info

        self.assertEqual(extract_firmware_info(None), (None, None))

    def test_returns_none_none_on_unexpected_metadata_shape(self):
        """Given hw_model isn't a valid enum value (e.g. a stale/unknown
        int from an untested firmware build), Then extraction fails
        closed to (None, None) rather than propagating the exception -
        firmware info is never worth failing a connection or probe
        over."""
        from core.meshtastic_utils import extract_firmware_info

        iface = unittest.mock.MagicMock()
        iface.metadata.firmware_version = '2.6.11.60ec05e'
        iface.metadata.hw_model = 99999

        self.assertEqual(extract_firmware_info(iface), (None, None))


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
