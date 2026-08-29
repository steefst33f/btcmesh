#!/usr/bin/env python3
"""
Tests for BTCMesh MeshCore Utilities (core/meshcore_utils.py).

Mirrors tests/test_meshtastic_utils.py's TestProbeDeviceIdentity shape -
candidate-port enumeration is transport-agnostic and tested once in
tests/test_device_scan.py instead (Story 30.4).
"""
import unittest
import unittest.mock


class TestProbeDeviceIdentity(unittest.TestCase):
    """Tests for probe_device_identity()."""

    def test_probe_device_identity_exists(self):
        from core.meshcore_utils import probe_device_identity
        self.assertTrue(callable(probe_device_identity))

    def test_returns_node_id_and_name_on_successful_connect(self):
        """Given a transport that connects successfully, Then returns a
        ProbedDevice with node_id, name (read straight off
        local_node_name - no separate call needed, unlike Meshtastic's
        get_own_node_name(iface)), and hw_model (Issue 54 -
        get_device_model()'s DEVICE_INFO round-trip), and disconnects
        afterward."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = 'a1b2c3d4e5f6'
        mock_transport.local_node_name = 'MC Node'
        mock_transport.get_device_model.return_value = 'Heltec V3'

        with unittest.mock.patch(
            'transport.meshcore_serial.MeshCoreSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ):
            from core.meshcore_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, 'a1b2c3d4e5f6')
        self.assertEqual(result.name, 'MC Node')
        self.assertEqual(result.hw_model, 'Heltec V3')
        mock_transport.connect.assert_called_once_with('/dev/cu.usbserial-0001')
        mock_transport.get_device_model.assert_called_once()
        mock_transport.disconnect.assert_called_once()

    def test_returns_node_id_with_no_name_when_device_has_none_set(self):
        """Given a device with no configured name (local_node_name is
        None), Then the ProbedDevice still carries the node_id."""
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = 'a1b2c3d4e5f6'
        mock_transport.local_node_name = None

        with unittest.mock.patch(
            'transport.meshcore_serial.MeshCoreSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ):
            from core.meshcore_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-0001')

        self.assertEqual(result.node_id, 'a1b2c3d4e5f6')
        self.assertIsNone(result.name)

    def test_returns_empty_identity_when_connect_fails(self):
        """Given connect() raises TransportConnectionError (e.g. not a real
        MeshCore device, already in use, or timed out), Then returns
        ProbedDevice(None, None) without raising, and still disconnects
        (safe no-op)."""
        from transport.base import TransportConnectionError

        mock_transport = unittest.mock.MagicMock()
        mock_transport.connect.side_effect = TransportConnectionError("Failed to connect")

        with unittest.mock.patch(
            'transport.meshcore_serial.MeshCoreSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value=None
        ):
            from core.meshcore_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-relay')

        self.assertIsNone(result.node_id)
        self.assertIsNone(result.name)
        mock_transport.disconnect.assert_called_once()

    def test_returns_relay_board_identity_without_attempting_meshcore_connect(self):
        """Given the candidate is confirmed to be the Story 26.7 relay
        board (its firmware reports a real hardware-derived unique ID),
        Then probe_device_identity() returns immediately with node_id set
        to that ID (prefixed '#', never confused with a real MeshCore
        public-key-prefix node ID) - WITHOUT ever attempting the slow
        MeshCore connect."""
        from core.meshcore_utils import RELAY_BOARD_NAME

        mock_transport = unittest.mock.MagicMock()

        with unittest.mock.patch(
            'transport.meshcore_serial.MeshCoreSerialTransport',
            return_value=mock_transport,
        ), unittest.mock.patch(
            'transport.power_control.probe_relay_board_id', return_value='246F28AECB34'
        ) as mock_probe_relay:
            from core.meshcore_utils import probe_device_identity
            result = probe_device_identity('/dev/cu.usbserial-112440')

        mock_probe_relay.assert_called_once_with('/dev/cu.usbserial-112440')
        self.assertEqual(result.node_id, '#246F28AECB34')
        self.assertEqual(result.name, RELAY_BOARD_NAME)
        mock_transport.connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
