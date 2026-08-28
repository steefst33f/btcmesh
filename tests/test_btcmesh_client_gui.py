#!/usr/bin/env python3
"""
Unit tests for btcmesh_client_gui.py

Tests the GUI logic, organized by story number from project/tasks.txt.
"""
import sys
import unittest
import unittest.mock
import queue
import logging

# Mock Kivy modules before importing btcmesh_client_gui
# This is necessary because Python loads the entire module (including Kivy imports)
# before extracting the specific functions we want to test
# These mocks are needed to also be able to run the tests in an environment
# without Kivy installed (like a CI server), otherwise they would fail.

# Create proper base classes for Kivy widgets to allow class inheritance
class MockCanvas:
    """Mock canvas for Kivy widgets."""
    def __init__(self):
        self.before = MockCanvasContext()


class MockCanvasContext:
    """Mock canvas context manager."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockBoxLayout:
    """Mock base class for BoxLayout to allow proper class inheritance."""
    def __init__(self, **kwargs):
        self.canvas = MockCanvas()
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = 100

    def add_widget(self, widget):
        pass

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockScrollView:
    """Mock base class for ScrollView."""
    def __init__(self, **kwargs):
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = 100

    def add_widget(self, widget):
        pass

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockApp:
    """Mock base class for App."""
    def __init__(self, **kwargs):
        pass

    def run(self):
        pass


kivy_mock = unittest.mock.MagicMock()
# get_color_from_hex should return a tuple like (r, g, b, a)
kivy_mock.get_color_from_hex = lambda _: (1, 1, 1, 1)

# Set up modules with proper base classes for inheritance
boxlayout_mock = unittest.mock.MagicMock()
boxlayout_mock.BoxLayout = MockBoxLayout

scrollview_mock = unittest.mock.MagicMock()
scrollview_mock.ScrollView = MockScrollView

app_mock = unittest.mock.MagicMock()
app_mock.App = MockApp

# Properties need to return actual values, not MagicMocks
properties_mock = unittest.mock.MagicMock()
properties_mock.StringProperty = lambda default='': default
properties_mock.BooleanProperty = lambda default=False: default

sys.modules['kivy'] = kivy_mock
sys.modules['kivy.app'] = app_mock
sys.modules['kivy.uix'] = kivy_mock
sys.modules['kivy.uix.boxlayout'] = boxlayout_mock
sys.modules['kivy.uix.label'] = kivy_mock
sys.modules['kivy.uix.textinput'] = kivy_mock
sys.modules['kivy.uix.button'] = kivy_mock
sys.modules['kivy.uix.scrollview'] = scrollview_mock
sys.modules['kivy.uix.popup'] = kivy_mock
sys.modules['kivy.uix.widget'] = kivy_mock
sys.modules['kivy.uix.togglebutton'] = kivy_mock
sys.modules['kivy.uix.spinner'] = kivy_mock
sys.modules['kivy.clock'] = kivy_mock
sys.modules['kivy.graphics'] = kivy_mock
sys.modules['kivy.core'] = kivy_mock
sys.modules['kivy.core.window'] = kivy_mock
sys.modules['kivy.core.clipboard'] = kivy_mock
sys.modules['kivy.properties'] = properties_mock
sys.modules['kivy.utils'] = kivy_mock

# Mock pubsub (used by btcmesh_cli)
pubsub_mock = unittest.mock.MagicMock()
sys.modules['pubsub'] = pubsub_mock

# Mock meshtastic (for device scanning tests)
meshtastic_mock = unittest.mock.MagicMock()
meshtastic_mock.util = unittest.mock.MagicMock()
meshtastic_mock.util.blacklistVids = []
meshtastic_mock.util.eliminate_duplicate_port = lambda ports: ports
sys.modules['meshtastic'] = meshtastic_mock
sys.modules['meshtastic.util'] = meshtastic_mock.util
sys.modules['meshtastic.serial_interface'] = unittest.mock.MagicMock()

# Default serial port enumeration to "no devices" so tests that don't scan
# explicitly aren't affected by whatever hardware happens to be attached to
# the machine running the suite; per-test patches override this as needed.
_comports_patcher = unittest.mock.patch(
    'serial.tools.list_ports.comports', return_value=[]
)
_comports_patcher.start()


def tearDownModule():
    """Undo this file's module-level meshtastic/serial mocking once all of
    its tests have run, so it doesn't leak into other test files that need
    the real meshtastic.util (e.g. eliminate_duplicate_port) or real
    serial.tools.list_ports.comports - discovered via a real bug this
    caused for Story 26.3's tests when run as part of the full suite.

    Kivy/pubsub mocks are deliberately left in place - nothing else in the
    codebase touches real 'kivy', so they're harmless to leave, and they
    must exist before this file's own module-level `from btcmesh_client_gui
    import ...` below anyway.
    """
    _comports_patcher.stop()
    for mod in ('meshtastic', 'meshtastic.util', 'meshtastic.serial_interface'):
        sys.modules.pop(mod, None)


from btcmesh_client_gui import (
    get_log_color,
    process_result,
    validate_send_inputs,
    ResultAction,
    NO_DEVICES_TEXT,
    SCANNING_TEXT,
    SELECT_DEVICE_TEXT,
    CONNECT_MAX_ATTEMPTS,
    NO_NODES_TEXT,
    MANUAL_ENTRY_TEXT,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_SUCCESS,
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_DISCONNECTED,
    ConnectionState,
    STATE_DISCONNECTED,
)


# =============================================================================
# Story 9.1: Implement Send Transaction Button
# Tests for input validation before sending transactions
# =============================================================================

class TestSendButtonValidationStory91(unittest.TestCase):
    """Tests for validate_send_inputs() - Story 9.1: Send Transaction Button.

    2026-08-23 revision: validate_send_inputs() no longer checks
    connection readiness or the self-send case - connecting is now part
    of the send flow itself (see project/plans/story_27_1.md's
    "Architecture Revision" section), so those two checks moved to
    _send_transaction_thread, covered separately below
    (TestConnectAndSendFlow)."""

    def test_empty_destination_returns_error(self):
        """Given empty destination, Then returns error message."""
        result = validate_send_inputs("", "aabbccdd")
        self.assertEqual(result, "Enter destination node ID")

    def test_destination_without_exclamation_returns_error(self):
        """Given destination without '!', Then returns error message."""
        result = validate_send_inputs("abc123", "aabbccdd")
        self.assertEqual(result, "Destination must start with '!'")

    def test_empty_tx_hex_returns_error(self):
        """Given empty tx_hex, Then returns error message."""
        result = validate_send_inputs("!abc123", "")
        self.assertEqual(result, "Enter transaction hex")

    def test_odd_length_tx_hex_returns_error(self):
        """Given tx_hex with odd length, Then returns error message."""
        result = validate_send_inputs("!abc123", "aabbccd")
        self.assertEqual(result, "Hex must have even length")

    def test_invalid_hex_characters_returns_error(self):
        """Given tx_hex with invalid characters, Then returns error message."""
        result = validate_send_inputs("!abc123", "gghhiijj")
        self.assertEqual(result, "Invalid hex characters")

    def test_valid_inputs_returns_none(self):
        """Given all valid inputs, Then returns None."""
        result = validate_send_inputs("!abc123", "aabbccdd")
        self.assertIsNone(result)

    def test_validation_order_checks_dest_first(self):
        """Given multiple invalid inputs, Then checks destination first."""
        result = validate_send_inputs("", "")
        self.assertEqual(result, "Enter destination node ID")

    def test_validation_order_checks_dest_format_second(self):
        """Given invalid dest format and other errors, Then checks dest format second."""
        result = validate_send_inputs("abc", "")
        self.assertEqual(result, "Destination must start with '!'")

    def test_validation_order_checks_tx_hex_third(self):
        """Given valid destination and empty tx_hex, Then checks tx_hex third."""
        result = validate_send_inputs("!abc123", "")
        self.assertEqual(result, "Enter transaction hex")

    def test_whitespace_only_destination_returns_error(self):
        """Given whitespace-only destination (after strip), Then returns error."""
        result = validate_send_inputs("", "aabbccdd")
        self.assertEqual(result, "Enter destination node ID")

    def test_dry_run_still_validates_inputs(self):
        """Given invalid hex, Then still returns an error regardless of
        dry-run status - dry_run is no longer a validate_send_inputs()
        parameter at all (Story 6.5's original intent - dry run still
        validates destination/tx_hex - now holds unconditionally, since
        there's no longer a connection-readiness check to skip)."""
        result = validate_send_inputs("!abc123", "gghhiijj")
        self.assertEqual(result, "Invalid hex characters")


# =============================================================================
# Story 10.1: Implement Connection Status Display
# Tests for connection status result processing
# =============================================================================

class TestConnectionStatusStory101(unittest.TestCase):
    """Tests for connection result processing - Story 10.1: Connection Status Display."""

    def test_connected_result_sets_connection_info(self):
        """Given 'connected' result, Then sets connection text, color, and stores iface."""
        mock_iface = unittest.mock.MagicMock()
        result = ('connected', mock_iface, '!abc123')

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected (!abc123)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)
        self.assertEqual(action.store_iface, mock_iface)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Connected to Meshtastic device: !abc123', action.log_messages[0][0])

    # Note: 'connection_failed'/'connection_error'/'connection_initializing'
    # were process_result() result types produced only by the old
    # _init_meshtastic() - removed along with it in the 2026-08-23 revision
    # (see project/plans/story_27_1.md's "Architecture Revision" section).
    # Connect failures during Send now surface as a plain 'error' result
    # instead (TestConnectAndSendFlow covers this).


# =============================================================================
# Story 10.2: Implement Scrollable Status Log
# Tests for log message display, color coding, and message handling
# =============================================================================


# =============================================================================
# Story 10.3: Implement Success/Failure Popups
# Tests for popup triggering
# =============================================================================

class TestPopupsStory103(unittest.TestCase):
    """Tests for success/failure popup triggering - Story 10.3: Success/Failure Popups."""

    # Note: 'tx_success' and 'print' were dead process_result() result
    # types (Issue 35) - removed along with their branches. The success
    # popup path for the current 'send_result' type is covered by
    # test_send_result_success_shows_popup below.

    def test_error_result_stops_sending(self):
        """Given 'error' result, Then stops sending and shows error in log."""
        result = ('error', 'Something went wrong')

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIn('Something went wrong', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)


# =============================================================================
# Story 22.2: TransactionSender Result Types
# Tests for TransactionSender result types (chunk_sending, progress, wire_sent, etc)
# =============================================================================

class TestTransactionSenderResultsStory222(unittest.TestCase):
    """Tests for TransactionSender result types - Story 22.2."""

    def test_chunk_sending_first_attempt(self):
        """Given chunk_sending result with attempt=1, Then shows 'Sending chunk X/Y...'."""
        result = ('chunk_sending', 1, 3, 1)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Sending chunk 1/3', action.log_messages[0][0])
        self.assertNotIn('retry', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)

    def test_chunk_sending_with_retry(self):
        """Given chunk_sending result with attempt=2, Then shows retry message."""
        result = ('chunk_sending', 2, 3, 2)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Sending chunk 2/3', action.log_messages[0][0])
        self.assertIn('retry 1', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)

    def test_chunk_sending_with_multiple_retries(self):
        """Given chunk_sending result with attempt=3, Then shows correct retry count."""
        result = ('chunk_sending', 1, 5, 3)

        action = process_result(result)

        self.assertIn('retry 2', action.log_messages[0][0])

    def test_wire_sent_shows_protocol_detail(self):
        """Given wire_sent result, Then shows arrow and wire format in secondary color."""
        wire_format = 'BTC_TX|abc123|1/3|020000...'
        result = ('wire_sent', wire_format)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('->', action.log_messages[0][0])
        self.assertIn(wire_format, action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_SECONDARY)

    def test_progress_intermediate_chunk(self):
        """Given progress for chunk 2 of 3, Then shows 'Chunk 2/3 sent'."""
        result = ('progress', 2, 3)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertEqual(action.log_messages[0][0], 'Chunk 2/3 sent')
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)
        self.assertFalse(action.stop_sending)

    def test_progress_final_chunk(self):
        """Given progress for final chunk, Then shows waiting message."""
        result = ('progress', 3, 3)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('waiting for broadcast', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_PRIMARY)
        self.assertFalse(action.stop_sending)

    def test_wire_received_shows_incoming_message(self):
        """Given wire_received result, Then shows arrow and message in secondary color."""
        message = 'BTC_CHUNK_ACK|abc123|2|REQUEST_CHUNK|3'
        result = ('wire_received', message)

        action = process_result(result)

        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('<-', action.log_messages[0][0])
        self.assertIn(message, action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_SECONDARY)

    def test_send_result_success_shows_popup(self):
        """Given send_result with success=True, Then shows popup and stops sending."""
        from client.sender import SendResult
        txid = 'abc123def456789'
        result = ('send_result', SendResult(success=True, session_id='sess1', txid=txid))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertEqual(action.show_success_popup, txid)
        self.assertEqual(len(action.log_messages), 0)  # No error message

    def test_send_result_error_shows_message(self):
        """Given send_result with error, Then shows error message and stops sending."""
        from client.sender import SendResult
        result = ('send_result', SendResult(
            success=False,
            session_id='sess1',
            error='Insufficient fee'
        ))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('Insufficient fee', action.log_messages[0][0])
        self.assertEqual(action.log_messages[0][1], COLOR_ERROR)

    def test_send_result_aborted_by_user(self):
        """Given send_result with abort, Then shows abort message."""
        from client.sender import SendResult
        result = ('send_result', SendResult(
            success=False,
            session_id='sess1',
            error='Aborted by user'
        ))

        action = process_result(result)

        self.assertTrue(action.stop_sending)
        self.assertIsNone(action.show_success_popup)
        self.assertEqual(len(action.log_messages), 1)
        self.assertIn('aborted', action.log_messages[0][0].lower())
        self.assertEqual(action.log_messages[0][1], COLOR_WARNING)



# Story 11.1: Device Selection Dropdown
# Tests for Meshtastic device scanning and selection
# =============================================================================

class TestDeviceSelectionStory111(unittest.TestCase):
    """Tests for device selection dropdown - Story 11.1: Device Selection Dropdown.

    scan_serial_devices()'s own behavior (VID-blacklist filtering,
    import/exception handling) is tested once, directly, in
    tests/test_device_scan.py - btcmesh_client_gui.py no longer imports
    it under a Meshtastic-specific name (Story 30.4 cleanup), so there's
    nothing GUI-specific left to test here beyond these constants."""

    def test_no_devices_text_constant(self):
        """Verify NO_DEVICES_TEXT constant is defined correctly."""
        self.assertEqual(NO_DEVICES_TEXT, "No devices found")

    def test_scanning_text_constant(self):
        """Verify SCANNING_TEXT constant is defined correctly."""
        self.assertEqual(SCANNING_TEXT, "Scanning...")


# =============================================================================
# Device connection retry + first-device-selection fixes
# Tests for issues found while testing the scan_meshtastic_devices() fix:
# a transient connect error left the GUI stuck forever, and the first device
# in a multi-device list couldn't be selected until a different device was
# picked first (see project/issues.txt Issue 10/11).
# =============================================================================

class TestDeviceConnectionRetryAndSelectionFix(unittest.TestCase):
    """Tests for connection retry logic and multi-device placeholder text."""

    class _ImmediateThread:
        """Runs the thread target synchronously instead of actually threading,
        so tests stay deterministic and don't need real background threads."""

        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    def _drain(self, q):
        results = []
        while not q.empty():
            results.append(q.get_nowait())
        return results

    def test_connect_with_retry_retries_transient_error_then_succeeds(self):
        """Given a transient error on the first attempt and success on the
        second, Then it retries instead of giving up immediately, and
        returns the connected transport."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        failing_transport = unittest.mock.MagicMock()
        failing_transport.connect.side_effect = TransportConnectionError(
            "Resource temporarily unavailable"
        )

        succeeding_transport = unittest.mock.MagicMock()
        succeeding_transport.connect.return_value = None
        succeeding_transport.local_node_id = "!12345678"

        transports = [failing_transport, succeeding_transport]

        with unittest.mock.patch('btcmesh_client_gui.get_transport', side_effect=transports), \
             unittest.mock.patch('btcmesh_client_gui.probe_relay_board_id', return_value=None), \
             unittest.mock.patch('btcmesh_client_gui.time.sleep'):
            result = btcmesh_client_gui.BTCMeshGUI._connect_with_retry(gui, '/dev/ttyFake')

        self.assertIs(result, succeeding_transport)
        log_messages = [r[1] for r in self._drain(gui.result_queue) if r[0] == 'log']
        self.assertTrue(any('initializing' in m.lower() for m in log_messages))

    def test_connect_with_retry_raises_after_max_attempts(self):
        """Given a persistently transient error, Then after CONNECT_MAX_ATTEMPTS
        it raises TransportConnectionError instead of retrying forever
        (regression test for the GUI getting permanently stuck - see
        Issue 10/11)."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        always_failing_transport = unittest.mock.MagicMock()
        always_failing_transport.connect.side_effect = TransportConnectionError(
            "Resource temporarily unavailable"
        )

        with unittest.mock.patch('btcmesh_client_gui.get_transport', return_value=always_failing_transport), \
             unittest.mock.patch('btcmesh_client_gui.probe_relay_board_id', return_value=None), \
             unittest.mock.patch('btcmesh_client_gui.time.sleep'):
            with self.assertRaises(TransportConnectionError):
                btcmesh_client_gui.BTCMeshGUI._connect_with_retry(gui, '/dev/ttyFake')

        self.assertEqual(always_failing_transport.connect.call_count, CONNECT_MAX_ATTEMPTS)

    def test_connect_with_retry_rejects_relay_board_without_attempting_connect(self):
        """Issue 37 follow-up: given the port is confirmed to be the relay
        board, Then _connect_with_retry() raises immediately with a clear
        message instead of attempting a Meshtastic connect that could
        never succeed - and would otherwise cost a full ~30s timeout for
        nothing."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        with unittest.mock.patch('btcmesh_client_gui.get_transport') as mock_get_transport, \
             unittest.mock.patch('btcmesh_client_gui.probe_relay_board_id', return_value='246F28AECB34') as mock_probe_relay:
            with self.assertRaises(TransportConnectionError) as ctx:
                btcmesh_client_gui.BTCMeshGUI._connect_with_retry(gui, '/dev/ttyRelay')

        mock_probe_relay.assert_called_once_with('/dev/ttyRelay')
        self.assertIn("relay board", str(ctx.exception))
        mock_get_transport.assert_not_called()

    def test_devices_found_multiple_sets_placeholder(self):
        """Given multiple devices found, Then the spinner shows the
        select-a-device placeholder and its values list the raw paths."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()

        devices = ['/dev/ttyUSB0', '/dev/ttyACM0']
        with unittest.mock.patch('btcmesh_client_gui.probe_devices_in_background'):
            btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('devices_found', devices))

        self.assertEqual(gui.device_spinner.values, devices)
        self.assertEqual(gui.device_spinner.text, SELECT_DEVICE_TEXT)


# =============================================================================
# Story 27.2: Node ID Display in the Client GUI's Device Dropdown
# Tests for probing device node IDs in the background and reflecting them in
# the device dropdown, without disrupting device selection/connection.
# =============================================================================

class TestNodeIdDisplayStory272(unittest.TestCase):
    """Tests for node ID/name display in the client GUI's device dropdown -
    the GUI-specific wiring around gui.gui_common's shared device-selection
    functions. The shared functions' own logic (dedup rules, reverse
    lookup, relabeling) is tested independently in tests/test_gui_common.py
    - these tests only verify this file calls them correctly, per the
    2026-08-23 revision (project/plans/story_27_1.md's "Architecture
    Revision" section)."""

    def test_devices_found_multiple_builds_devices_list_and_probes(self):
        """Given multiple devices found, Then self.devices is built with
        node_id=None/name=None for each, and probing is kicked off via the
        shared probe_devices_in_background()."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()

        devices = ['/dev/ttyUSB0', '/dev/ttyACM0']
        with unittest.mock.patch('btcmesh_client_gui.probe_devices_in_background') as mock_probe:
            btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('devices_found', devices))

        self.assertEqual(
            gui.devices,
            [
                {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
                {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
            ],
        )
        mock_probe.assert_called_once_with(
            gui.devices, gui.result_queue,
            transport_name=gui.selected_transport, should_abort=unittest.mock.ANY,
        )

    def test_devices_found_single_auto_selects_without_separate_probe(self):
        """Given a single device found, Then it's auto-selected but not
        auto-connected (2026-08-23 revision), and NOT separately probed
        either (2026-08-23 known-nodes-staleness fix): setting .text
        fires on_device_selected on a real spinner, whose own brief
        connect fetches identity for free - probing the same sole device
        again at the same time would just race itself over one serial
        port. See TestDeviceSelectedFetchFlow for on_device_selected's
        own behavior."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()

        with unittest.mock.patch('btcmesh_client_gui.probe_devices_in_background') as mock_probe:
            btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('devices_found', ['/dev/ttyUSB0']))

        self.assertEqual(gui.device_spinner.text, '/dev/ttyUSB0')
        mock_probe.assert_not_called()

    def test_device_identity_result_updates_matching_device_and_dedupes(self):
        """Given a device_identity probe result, Then the matching
        device's node_id/name are updated, dedup runs via the shared
        dedupe_devices_by_node_id() (node_id is truthy), and the spinner
        labels are refreshed via the shared refresh_device_spinner_labels()
        - passing on_device_selected as the selection_handler to protect
        against a spurious refetch on relabel (2026-08-23 known-nodes-
        staleness fix)."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]
        gui.device_spinner = unittest.mock.MagicMock()

        with unittest.mock.patch(
            'btcmesh_client_gui.dedupe_devices_by_node_id',
            return_value=(gui.devices, None),
        ) as mock_dedupe, unittest.mock.patch(
            'btcmesh_client_gui.refresh_device_spinner_labels'
        ) as mock_refresh:
            btcmesh_client_gui.BTCMeshGUI._handle_result(
                gui, ('device_identity', '/dev/ttyACM0', '!7c5b4418', 'Meshtastic 4418')
            )

        self.assertIsNone(gui.devices[0]['node_id'])
        self.assertEqual(gui.devices[1]['node_id'], '!7c5b4418')
        self.assertEqual(gui.devices[1]['name'], 'Meshtastic 4418')
        mock_dedupe.assert_called_once_with(gui.devices, keep_path='/dev/ttyACM0')
        mock_refresh.assert_called_once_with(
            gui.device_spinner, gui.devices, selection_handler=gui.on_device_selected
        )

    def test_device_identity_none_skips_dedupe(self):
        """Given a probe result of node_id=None/name=None (not a real
        Meshtastic device, or connect failed), Then dedup is skipped
        (nothing to dedupe against a None node_id), but labels still
        refresh."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.device_spinner = unittest.mock.MagicMock()

        with unittest.mock.patch('btcmesh_client_gui.dedupe_devices_by_node_id') as mock_dedupe, \
             unittest.mock.patch('btcmesh_client_gui.refresh_device_spinner_labels') as mock_refresh:
            btcmesh_client_gui.BTCMeshGUI._handle_result(
                gui, ('device_identity', '/dev/ttyUSB0', None, None)
            )

        self.assertIsNone(gui.devices[0]['node_id'])
        self.assertIsNone(gui.devices[0]['name'])
        mock_dedupe.assert_not_called()
        mock_refresh.assert_called_once()

    def test_on_send_pressed_resolves_device_path_from_display(self):
        """Given a labeled 'name (node_id)' selection, Then on_send_pressed
        resolves it to the real underlying path (via the shared
        device_path_from_display()) before starting the send thread, not
        the formatted display string - the actual regression risk this
        revision introduces if missed, since the send thread passes this
        straight to transport.connect()."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]
        gui.device_spinner = unittest.mock.MagicMock()
        gui.device_spinner.text = 'Meshtastic 4418 (!7c5b4418)'
        gui.dest_input.text = '!abcd1234'
        gui.tx_input.text = 'aabbccdd'
        gui.dry_run_toggle.state = 'normal'
        gui.status_log = unittest.mock.MagicMock()
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.selected_transport = "meshtastic"

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread') as mock_thread:
            btcmesh_client_gui.BTCMeshGUI.on_send_pressed(gui, None)

        args = mock_thread.call_args.kwargs['args']
        self.assertEqual(args[3], '/dev/ttyUSB0')


# =============================================================================
# _send_transaction_thread's connect-send-disconnect flow (2026-08-23
# revision - see project/plans/story_27_1.md's "Architecture Revision"
# section). Mirrors btcmesh_client_cli.py's run_send(): connect, send,
# disconnect in a finally - connecting is no longer a precondition checked
# before Send, it's part of the send flow itself.
# =============================================================================

class TestConnectAndSendFlow(unittest.TestCase):
    """Tests for _send_transaction_thread()'s connect/send/disconnect
    lifecycle."""

    def _make_gui(self):
        gui = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        return gui

    def _drain(self, q):
        results = []
        while not q.empty():
            results.append(q.get_nowait())
        return results

    def test_dry_run_never_connects(self):
        """Given dry_run=True, Then no connection is attempted at all -
        just the chunking preview."""
        import btcmesh_client_gui

        gui = self._make_gui()
        gui._run_preview = unittest.mock.MagicMock()

        with unittest.mock.patch('btcmesh_client_gui.MeshtasticSerialTransport') as mock_transport_cls:
            btcmesh_client_gui.BTCMeshGUI._send_transaction_thread(
                gui, '!abcd1234', 'aabbccdd', True, '/dev/ttyUSB0'
            )

        mock_transport_cls.assert_not_called()
        gui._run_preview.assert_called_once_with('aabbccdd')

    def test_successful_send_connects_sends_and_disconnects(self):
        """Given a successful connect, Then it pushes 'connected', sends
        via TransactionSender, pushes 'send_result', then always
        disconnects and pushes 'disconnected'."""
        import btcmesh_client_gui

        gui = self._make_gui()
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'
        gui._connect_with_retry = unittest.mock.MagicMock(return_value=mock_transport)

        mock_sender = unittest.mock.MagicMock()
        mock_result = unittest.mock.MagicMock(success=True, txid='abc123')
        mock_sender.send_transaction.return_value = mock_result

        with unittest.mock.patch(
            'btcmesh_client_gui.TransactionSender', return_value=mock_sender
        ), unittest.mock.patch(
            'btcmesh_client_gui.get_own_node_name', return_value='Meshtastic 4418'
        ):
            btcmesh_client_gui.BTCMeshGUI._send_transaction_thread(
                gui, '!abcd1234', 'aabbccdd', False, '/dev/ttyUSB0'
            )

        gui._connect_with_retry.assert_called_once_with('/dev/ttyUSB0')
        mock_sender.send_transaction.assert_called_once()
        mock_transport.disconnect.assert_called_once()
        self.assertIsNone(gui.transport)
        self.assertIsNone(gui.iface)

        result_types = [r[0] for r in self._drain(gui.result_queue)]
        self.assertEqual(
            result_types,
            ['connected', 'send_result', 'disconnected'],
        )

    def test_connect_failure_pushes_error_and_never_sends(self):
        """Given _connect_with_retry raises, Then a plain 'error' result is
        pushed and TransactionSender is never constructed - no
        'disconnected' either, since nothing was ever connected."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = self._make_gui()
        gui._connect_with_retry = unittest.mock.MagicMock(
            side_effect=TransportConnectionError("No Meshtastic device found")
        )

        with unittest.mock.patch('btcmesh_client_gui.TransactionSender') as mock_sender_cls:
            btcmesh_client_gui.BTCMeshGUI._send_transaction_thread(
                gui, '!abcd1234', 'aabbccdd', False, '/dev/ttyUSB0'
            )

        mock_sender_cls.assert_not_called()
        results = self._drain(gui.result_queue)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 'error')
        self.assertIn('No Meshtastic device found', results[0][1])

    def test_self_send_rejected_after_connecting(self):
        """Given the destination matches the just-connected device's own
        node ID, Then a 'Cannot send to your own node' error is pushed,
        TransactionSender is never used, but the transport is still
        disconnected (self-send is discovered only after connecting,
        since the own node ID isn't known before then)."""
        import btcmesh_client_gui

        gui = self._make_gui()
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!abcd1234'
        gui._connect_with_retry = unittest.mock.MagicMock(return_value=mock_transport)

        with unittest.mock.patch(
            'btcmesh_client_gui.TransactionSender'
        ) as mock_sender_cls, unittest.mock.patch(
            'btcmesh_client_gui.get_own_node_name', return_value=None
        ):
            btcmesh_client_gui.BTCMeshGUI._send_transaction_thread(
                gui, '!ABCD1234', 'aabbccdd', False, '/dev/ttyUSB0'
            )

        mock_sender_cls.assert_not_called()
        mock_transport.disconnect.assert_called_once()
        result_types = [r[0] for r in self._drain(gui.result_queue)]
        self.assertEqual(result_types, ['connected', 'error', 'disconnected'])

    def test_disconnect_happens_even_when_send_raises(self):
        """Given sender.send_transaction() raises, Then the transport is
        still disconnected and 'disconnected' is still pushed - the
        finally block covers exceptions, not just the happy path."""
        import btcmesh_client_gui

        gui = self._make_gui()
        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'
        gui._connect_with_retry = unittest.mock.MagicMock(return_value=mock_transport)

        mock_sender = unittest.mock.MagicMock()
        mock_sender.send_transaction.side_effect = RuntimeError("boom")

        with unittest.mock.patch(
            'btcmesh_client_gui.TransactionSender', return_value=mock_sender
        ), unittest.mock.patch(
            'btcmesh_client_gui.get_own_node_name', return_value='Meshtastic 4418'
        ):
            btcmesh_client_gui.BTCMeshGUI._send_transaction_thread(
                gui, '!abcd1234', 'aabbccdd', False, '/dev/ttyUSB0'
            )

        mock_transport.disconnect.assert_called_once()
        result_types = [r[0] for r in self._drain(gui.result_queue)]
        self.assertEqual(result_types, ['connected', 'error', 'disconnected'])


# =============================================================================
# Story 11.2: Known Nodes Dropdown for Destination
# Tests for extracting and formatting known nodes from Meshtastic interface
# =============================================================================

class TestKnownNodesStory112(unittest.TestCase):
    """Tests for known nodes dropdown - Story 11.2."""

    def _create_mock_node(self, node_id, long_name, short_name, last_heard, hops_away=1):
        """Helper to create a mock node structure."""
        return {
            'user': {
                'id': node_id,
                'longName': long_name,
                'shortName': short_name,
            },
            'lastHeard': last_heard,
            'hopsAway': hops_away,
        }

    def test_get_known_nodes_returns_empty_list_when_no_nodes(self):
        """Given interface has no nodes, Then returns empty list."""
        from btcmesh_client_gui import get_known_nodes
        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = {}
        mock_iface.myInfo.my_node_num = 12345678

        result = get_known_nodes(mock_iface)

        self.assertEqual(result, [])

    def test_get_known_nodes_returns_empty_list_when_nodes_is_none(self):
        """Given interface.nodes is None, Then returns empty list."""
        from btcmesh_client_gui import get_known_nodes
        mock_iface = unittest.mock.MagicMock()
        mock_iface.nodes = None
        mock_iface.myInfo.my_node_num = 12345678

        result = get_known_nodes(mock_iface)

        self.assertEqual(result, [])

    def test_get_known_nodes_extracts_node_info(self):
        """Given interface has nodes, Then extracts id, name, lastHeard."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'Node One', 'NO1', now - 100),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!abcd1234')
        self.assertEqual(result[0]['name'], 'Node One')
        self.assertEqual(result[0]['lastHeard'], now - 100)

    def test_get_known_nodes_filters_out_own_node(self):
        """Given interface has own node in list, Then filters it out."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234  # Own node
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'My Node', 'MYN', now - 100),
            '!efef5678': self._create_mock_node('!efef5678', 'Other Node', 'OTH', now - 200),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!efef5678')

    def test_get_known_nodes_sorts_by_last_heard_descending(self):
        """Given multiple nodes, Then sorts by lastHeard (most recent first)."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!oldest00': self._create_mock_node('!oldest00', 'Oldest', 'OLD', now - 3600),
            '!newest00': self._create_mock_node('!newest00', 'Newest', 'NEW', now - 60),
            '!middle00': self._create_mock_node('!middle00', 'Middle', 'MID', now - 1800),
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]['id'], '!newest00')  # Most recent
        self.assertEqual(result[1]['id'], '!middle00')
        self.assertEqual(result[2]['id'], '!oldest00')  # Oldest

    def test_get_known_nodes_uses_short_name_if_no_long_name(self):
        """Given node has no longName, Then uses shortName."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': 'SHRT',
                },
                'lastHeard': now - 100,
                'hopsAway': 1,
            },
        }

        result = get_known_nodes(mock_iface)

        self.assertEqual(result[0]['name'], 'SHRT')

    def test_get_known_nodes_handles_missing_user_info(self):
        """Given node has no user info, Then handles gracefully."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!abcd1234': {
                'lastHeard': now - 100,
            },
        }

        result = get_known_nodes(mock_iface)

        # Should still include node but with node_id as name
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], '!abcd1234')

    def test_get_known_nodes_includes_is_recent_flag(self):
        """Given nodes with different lastHeard, Then includes is_recent flag."""
        from btcmesh_client_gui import get_known_nodes
        import time
        now = int(time.time())
        hours_24 = 24 * 60 * 60

        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 12345678
        mock_iface.nodes = {
            '!recent00': self._create_mock_node('!recent00', 'Recent', 'REC', now - 100),
            '!stale000': self._create_mock_node('!stale000', 'Stale', 'STL', now - hours_24 - 100),
        }

        result = get_known_nodes(mock_iface)

        recent_node = next(n for n in result if n['id'] == '!recent00')
        stale_node = next(n for n in result if n['id'] == '!stale000')

        self.assertTrue(recent_node['is_recent'])
        self.assertFalse(stale_node['is_recent'])

    def test_format_node_display_recent_node(self):
        """Given a recent node, Then displays name and id."""
        from btcmesh_client_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'Test Node', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertEqual(result, 'Test Node (!abcd1234)')

    def test_format_node_display_stale_node(self):
        """Given a stale node, Then displays name and id (same as recent)."""
        from btcmesh_client_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'Test Node', 'lastHeard': 123456, 'is_recent': False}

        result = format_node_display(node)

        self.assertEqual(result, 'Test Node (!abcd1234)')

    def test_format_node_display_includes_name_and_id(self):
        """Given a node, Then includes name and id in display."""
        from btcmesh_client_gui import format_node_display
        node = {'id': '!abcd1234', 'name': 'My Relay', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertIn('My Relay', result)
        self.assertIn('!abcd1234', result)

    def test_format_node_display_format(self):
        """Given a node, Then formats as 'name (id)'."""
        from btcmesh_client_gui import format_node_display
        node = {'id': '!efef5678', 'name': 'Relay Server', 'lastHeard': 123456, 'is_recent': True}

        result = format_node_display(node)

        self.assertEqual(result, 'Relay Server (!efef5678)')

    def test_no_nodes_text_constant(self):
        """Verify NO_NODES_TEXT constant is defined correctly."""
        self.assertEqual(NO_NODES_TEXT, "No nodes found")

    def test_manual_entry_text_constant(self):
        """Verify MANUAL_ENTRY_TEXT constant is defined correctly."""
        self.assertEqual(MANUAL_ENTRY_TEXT, "Enter manually...")


# =============================================================================
# Issue 39: non-blocking busy indicator for _scan_devices()
# =============================================================================

class TestScanDevicesBusyIndicator(unittest.TestCase):
    """Tests for _scan_devices()'s device_busy wiring (Issue 39)."""

    class _ImmediateThread:
        """Runs the thread target synchronously so tests stay deterministic."""

        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    def test_scan_shows_busy_indicator_without_disabling_the_spinner(self):
        """Given a scan starts, Then device_busy.start() is called and
        device_spinner.disabled is never touched - scanning has never
        blocked device selection, and this story doesn't change that."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock(disabled=False)
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.scan_serial_devices', return_value=['/dev/ttyUSB0']
             ):
            btcmesh_client_gui.BTCMeshGUI._scan_devices(gui)

        gui.device_busy.start.assert_called_once()
        self.assertFalse(gui.device_spinner.disabled)

    def test_devices_found_with_multiple_devices_keeps_busy_indicator_active(self):
        """Given devices_found reports more than one device, Then
        probe_devices_in_background() starts its own device_busy reason
        (own start()/stop() pair) - the indicator must not flash off
        just because the scan itself finished while probing continues."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.device_spinner = unittest.mock.MagicMock(disabled=False)
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        with unittest.mock.patch('btcmesh_client_gui.probe_devices_in_background') as mock_probe:
            btcmesh_client_gui.BTCMeshGUI._handle_result(
                gui, ('devices_found', ['/dev/ttyUSB0', '/dev/ttyACM0'])
            )

        mock_probe.assert_called_once()
        # Two independent reasons this session: _scan_devices()'s own
        # (not exercised here) plus this branch's own start() - then the
        # devices_found handler's own stop() for "the scan is done."
        # Only the shared stop() (for the scan itself) should have run
        # here; the probe's own start() must not have been immediately
        # cancelled out by it.
        self.assertEqual(gui.device_busy.start.call_count, 1)
        self.assertEqual(gui.device_busy.stop.call_count, 1)

    def test_device_probe_complete_stops_device_busy(self):
        """The multi-device identity-probe batch's own completion
        sentinel (pushed by probe_devices_in_background()) must stop
        device_busy - this is its only stop trigger."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('device_probe_complete',))
        gui.device_busy.stop.assert_called_once()

    def test_device_and_nodes_fetch_complete_stops_both_indicators(self):
        """on_device_selected()'s completion sentinel must stop both
        device_busy and nodes_busy - it fetches both in one thread."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('device_and_nodes_fetch_complete',))
        gui.device_busy.stop.assert_called_once()
        gui.nodes_busy.stop.assert_called_once()

    def test_known_nodes_fetch_complete_stops_only_nodes_busy(self):
        """on_refresh_nodes()'s completion sentinel must stop nodes_busy
        only - it never touches device_busy."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('known_nodes_fetch_complete',))
        gui.nodes_busy.stop.assert_called_once()
        gui.device_busy.stop.assert_not_called()


# =============================================================================
# Story 11.2 revised (2026-08-23): on-demand known-nodes fetch
# Tests for on_refresh_nodes()'s own brief connect/fetch/disconnect cycle -
# it no longer reads an ambient self.iface (see
# project/plans/story_27_1.md's "Architecture Revision" section).
# =============================================================================

class TestKnownNodesFetchFlow(unittest.TestCase):
    """Tests for on_refresh_nodes()'s connect-fetch-disconnect flow and
    _update_known_nodes()'s new (nodes) signature."""

    class _ImmediateThread:
        """Runs the thread target synchronously so tests stay deterministic."""

        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    def test_on_refresh_nodes_connects_fetches_and_disconnects(self):
        """Given the Scan-for-nodes button is pressed, Then it briefly
        connects to the currently selected device, fetches known nodes,
        pushes a known_nodes_fetched result, and disconnects."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]
        gui.device_spinner = unittest.mock.MagicMock()
        gui.device_spinner.text = 'Meshtastic 4418 (!7c5b4418)'
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        mock_transport = unittest.mock.MagicMock()
        mock_nodes = [{'id': '!11111111', 'name': 'Other', 'lastHeard': 0, 'is_recent': False}]

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.MeshtasticSerialTransport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch(
                 'btcmesh_client_gui.get_known_nodes', return_value=mock_nodes
             ) as mock_get_nodes:
            btcmesh_client_gui.BTCMeshGUI.on_refresh_nodes(gui, None)

        mock_transport.connect.assert_called_once_with('/dev/ttyUSB0')
        mock_get_nodes.assert_called_once_with(mock_transport._iface)
        mock_transport.disconnect.assert_called_once()
        results = []
        while not gui.result_queue.empty():
            results.append(gui.result_queue.get_nowait())
        self.assertIn(('known_nodes_fetched', mock_nodes), results)

    def test_on_refresh_nodes_shows_busy_indicator_without_disabling_anything(self):
        """Issue 39: on_refresh_nodes() must show the busy indicator via
        nodes_busy, but never disable node_spinner or dest_input - a
        user who already knows the destination node ID can keep typing
        while the fetch is in flight."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]
        gui.device_spinner = unittest.mock.MagicMock()
        gui.device_spinner.text = 'Meshtastic 4418 (!7c5b4418)'
        gui.node_spinner = unittest.mock.MagicMock(disabled=False)
        gui.dest_input = unittest.mock.MagicMock(disabled=False)
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        mock_transport = unittest.mock.MagicMock()

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.MeshtasticSerialTransport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch('btcmesh_client_gui.get_known_nodes', return_value=[]):
            btcmesh_client_gui.BTCMeshGUI.on_refresh_nodes(gui, None)

        gui.nodes_busy.start.assert_called_once()
        # stop() itself happens in _handle_result() once this sentinel is
        # drained (covered by test_known_nodes_fetch_complete_stops_only_nodes_busy)
        # - here we only need to confirm the sentinel was actually pushed.
        results = []
        while not gui.result_queue.empty():
            results.append(gui.result_queue.get_nowait())
        self.assertIn(('known_nodes_fetch_complete',), results)
        self.assertFalse(gui.node_spinner.disabled)
        self.assertFalse(gui.dest_input.disabled)

    def test_on_refresh_nodes_logs_error_and_disconnects_nothing_on_connect_failure(self):
        """Given the device fails to connect, Then a log error is pushed
        instead of a known_nodes_fetched result, and get_known_nodes() is
        never called."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.devices = []
        gui.device_spinner = unittest.mock.MagicMock()
        gui.device_spinner.text = 'Auto-detect'
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        mock_transport = unittest.mock.MagicMock()
        mock_transport.connect.side_effect = TransportConnectionError("No Meshtastic device found")

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.MeshtasticSerialTransport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch('btcmesh_client_gui.get_known_nodes') as mock_get_nodes:
            btcmesh_client_gui.BTCMeshGUI.on_refresh_nodes(gui, None)

        mock_get_nodes.assert_not_called()
        results = []
        while not gui.result_queue.empty():
            results.append(gui.result_queue.get_nowait())
        # Issue 39: known_nodes_fetch_complete always fires too, pairing
        # with nodes_busy.start() - even on this error path.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 'log')
        self.assertEqual(results[1], ('known_nodes_fetch_complete',))

    def test_on_refresh_nodes_skips_connect_for_relay_board(self):
        """Issue 37 follow-up: given the currently selected device is
        confirmed to be the relay board, Then on_refresh_nodes() logs a
        clear message instead of attempting a Meshtastic connect that
        could never succeed - and would otherwise cost a full ~30s
        timeout for nothing."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyRelay', 'node_id': None, 'name': 'Relay board (not a Meshtastic device)'}]
        gui.device_spinner = unittest.mock.MagicMock()
        gui.device_spinner.text = 'Relay board (not a Meshtastic device)'
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch('btcmesh_client_gui.MeshtasticSerialTransport') as mock_transport_cls, \
             unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value='246F28AECB34'
             ) as mock_probe_relay, \
             unittest.mock.patch('btcmesh_client_gui.get_known_nodes') as mock_get_nodes:
            btcmesh_client_gui.BTCMeshGUI.on_refresh_nodes(gui, None)

        mock_probe_relay.assert_called_once_with('/dev/ttyRelay')
        mock_transport_cls.assert_not_called()
        mock_get_nodes.assert_not_called()
        results = []
        while not gui.result_queue.empty():
            results.append(gui.result_queue.get_nowait())
        # Issue 39: known_nodes_fetch_complete always fires too, pairing
        # with nodes_busy.start() - even on this early-exit path.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 'log')
        self.assertIn('relay board', results[0][1])
        self.assertEqual(results[1], ('known_nodes_fetch_complete',))

    def test_update_known_nodes_applies_fetched_list(self):
        """Given a fetched nodes list, Then the destination dropdown is
        populated from it (the pure UI-update half of the old
        _update_known_nodes(), now taking the list as a parameter instead
        of reading self.iface)."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.node_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        nodes = [{'id': '!11111111', 'name': 'Relay', 'lastHeard': 0, 'is_recent': False}]

        btcmesh_client_gui.BTCMeshGUI._update_known_nodes(gui, nodes)

        self.assertEqual(gui.known_nodes, nodes)
        self.assertIn('Relay (!11111111)', gui.node_spinner.values)

    def test_update_known_nodes_empty_list_shows_no_nodes_option(self):
        """Given an empty fetched nodes list, Then the dropdown shows the
        no-nodes placeholder rather than an empty list."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.node_spinner = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()

        btcmesh_client_gui.BTCMeshGUI._update_known_nodes(gui, [])

        self.assertEqual(gui.node_spinner.values, [MANUAL_ENTRY_TEXT, NO_NODES_TEXT])


# =============================================================================
# Fix: Known-Nodes Staleness on Device Selection (2026-08-23)
# Tests for on_device_selected()'s combined identity+known-nodes fetch - see
# project/plans/story_27_1.md's section of the same name.
# =============================================================================

class TestDeviceSelectedFetchFlow(unittest.TestCase):
    """Tests for on_device_selected()'s connect-fetch-disconnect flow."""

    class _ImmediateThread:
        """Runs the thread target synchronously so tests stay deterministic."""

        def __init__(self, target=None, daemon=None, **kwargs):
            self._target = target

        def start(self):
            if self._target:
                self._target()

    def _drain(self, q):
        results = []
        while not q.empty():
            results.append(q.get_nowait())
        return results

    def test_ignores_sentinel_values(self):
        """Given a sentinel spinner text (no real device selected), Then
        nothing is fetched - no connection attempt at all."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()

        for text in (NO_DEVICES_TEXT, SCANNING_TEXT, SELECT_DEVICE_TEXT, ''):
            with unittest.mock.patch('btcmesh_client_gui.MeshtasticSerialTransport') as mock_transport_cls:
                btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, text)
            mock_transport_cls.assert_not_called()

    def test_selecting_a_device_fetches_identity_and_known_nodes(self):
        """Given a real device is selected, Then one connection fetches
        both its identity (pushed as device_identity) and its known nodes
        (pushed as known_nodes_fetched), then disconnects."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'
        mock_nodes = [{'id': '!11111111', 'name': 'Other', 'lastHeard': 0, 'is_recent': False}]

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.get_transport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch(
                 'btcmesh_client_gui.get_own_node_name', return_value='Meshtastic 4418'
             ), unittest.mock.patch(
                 'btcmesh_client_gui.get_known_nodes', return_value=mock_nodes
             ):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, '/dev/ttyUSB0')

        mock_transport.connect.assert_called_once_with('/dev/ttyUSB0')
        mock_transport.disconnect.assert_called_once()
        results = self._drain(gui.result_queue)
        self.assertIn(('device_identity', '/dev/ttyUSB0', '!7c5b4418', 'Meshtastic 4418'), results)
        self.assertIn(('known_nodes_fetched', mock_nodes), results)

    def test_shows_busy_indicators_without_disabling_anything(self):
        """Issue 39: on_device_selected() must show both busy indicators
        (it fetches identity and known nodes in one thread), but never
        disable device_spinner, node_spinner, or dest_input - a user who
        already knows what to pick/type shouldn't have to wait."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.device_spinner = unittest.mock.MagicMock(disabled=False)
        gui.node_spinner = unittest.mock.MagicMock(disabled=False)
        gui.dest_input = unittest.mock.MagicMock(disabled=False)
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.get_transport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch(
                 'btcmesh_client_gui.get_own_node_name', return_value='Meshtastic 4418'
             ), unittest.mock.patch('btcmesh_client_gui.get_known_nodes', return_value=[]):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, '/dev/ttyUSB0')

        gui.device_busy.start.assert_called_once()
        gui.nodes_busy.start.assert_called_once()
        # stop() itself happens in _handle_result() once this sentinel is
        # drained (covered by test_device_and_nodes_fetch_complete_stops_both_indicators)
        # - here we only need to confirm the sentinel was actually pushed.
        self.assertIn(('device_and_nodes_fetch_complete',), self._drain(gui.result_queue))
        self.assertFalse(gui.device_spinner.disabled)
        self.assertFalse(gui.node_spinner.disabled)
        self.assertFalse(gui.dest_input.disabled)

    def test_resolves_labeled_display_text_to_real_path(self):
        """Given the spinner already shows a labeled 'name (node_id)'
        entry (e.g. after a background probe resolved it), Then selecting
        it connects to the real underlying path, not the formatted
        string."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        mock_transport = unittest.mock.MagicMock()
        mock_transport.local_node_id = '!7c5b4418'

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.get_transport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ), unittest.mock.patch(
                 'btcmesh_client_gui.get_own_node_name', return_value='Meshtastic 4418'
             ), unittest.mock.patch('btcmesh_client_gui.get_known_nodes', return_value=[]):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(
                gui, None, 'Meshtastic 4418 (!7c5b4418)'
            )

        mock_transport.connect.assert_called_once_with('/dev/ttyUSB0')

    def test_connect_failure_logs_error_and_pushes_no_results(self):
        """Given the device fails to connect, Then a log error is pushed
        and neither device_identity nor known_nodes_fetched are."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        mock_transport = unittest.mock.MagicMock()
        mock_transport.connect.side_effect = TransportConnectionError("No Meshtastic device found")

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.get_transport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, '/dev/ttyUSB0')

        results = self._drain(gui.result_queue)
        # Issue 39: device_and_nodes_fetch_complete always fires too,
        # pairing with device_busy.start()/nodes_busy.start() - even on
        # this error path.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 'log')
        self.assertIn('No Meshtastic device found', results[0][1])
        self.assertEqual(results[1], ('device_and_nodes_fetch_complete',))

    def test_connect_failure_uses_friendly_error_wording(self):
        """Given a raw timeout exception, Then the logged message uses
        _friendly_connect_error()'s wording, not the raw "waiting for
        connection completion" text - which reads like a failed Send
        attempt the user never asked for (2026-08-23 follow-up fix)."""
        import btcmesh_client_gui
        from transport.base import TransportConnectionError

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        mock_transport = unittest.mock.MagicMock()
        mock_transport.connect.side_effect = TransportConnectionError(
            "Failed to connect: Timed out waiting for connection completion"
        )

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch(
                 'btcmesh_client_gui.get_transport', return_value=mock_transport
             ), unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value=None
             ):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, '/dev/ttyUSB0')

        results = self._drain(gui.result_queue)
        self.assertNotIn('waiting for connection completion', results[0][1])
        self.assertIn('did not respond', results[0][1])

    def test_clears_known_nodes_immediately_before_fetch_completes(self):
        """Given a device is selected, Then _update_known_nodes([]) is
        called synchronously right away, before the background fetch even
        starts - so the previous device's known nodes don't stay visible
        even briefly (2026-08-23 follow-up fix)."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.selected_transport = "meshtastic"

        call_order = []
        gui._update_known_nodes = unittest.mock.MagicMock(
            side_effect=lambda nodes: call_order.append(('clear', nodes))
        )

        with unittest.mock.patch(
            'btcmesh_client_gui.threading.Thread',
            side_effect=lambda target, daemon: call_order.append(('thread_started',)) or self._ImmediateThread(target, daemon),
        ), unittest.mock.patch('btcmesh_client_gui.get_transport'), \
             unittest.mock.patch('btcmesh_client_gui.probe_relay_board_id', return_value=None):
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(gui, None, '/dev/ttyUSB0')

        gui._update_known_nodes.assert_any_call([])
        self.assertEqual(call_order[0], ('clear', []))

    def test_selecting_relay_board_skips_connect_and_logs_clear_message(self):
        """Issue 37 follow-up: given the selected entry is confirmed to be
        the relay board, Then a clear message is logged instead of
        attempting a Meshtastic connect that could never succeed - and
        would otherwise cost a full ~30s timeout for nothing."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui.devices = [{'path': '/dev/ttyRelay', 'node_id': None, 'name': 'Relay board (not a Meshtastic device)'}]
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()

        with unittest.mock.patch('btcmesh_client_gui.threading.Thread', self._ImmediateThread), \
             unittest.mock.patch('btcmesh_client_gui.MeshtasticSerialTransport') as mock_transport_cls, \
             unittest.mock.patch(
                 'btcmesh_client_gui.probe_relay_board_id', return_value='246F28AECB34'
             ) as mock_probe_relay:
            btcmesh_client_gui.BTCMeshGUI.on_device_selected(
                gui, None, 'Relay board (not a Meshtastic device)'
            )

        mock_probe_relay.assert_called_once_with('/dev/ttyRelay')
        mock_transport_cls.assert_not_called()
        results = self._drain(gui.result_queue)
        # Issue 39: device_and_nodes_fetch_complete always fires too,
        # pairing with device_busy.start()/nodes_busy.start() - even on
        # this early-exit path.
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], 'log')
        self.assertIn('relay board', results[0][1])
        self.assertEqual(results[1], ('device_and_nodes_fetch_complete',))


# =============================================================================
# Pure helper: _friendly_connect_error()
# =============================================================================

class TestFriendlyConnectError(unittest.TestCase):
    """Tests for _friendly_connect_error(), shared by every brief
    background connect (Send, device-info fetch, known-nodes fetch) so
    error wording reads consistently regardless of which one failed."""

    def test_no_meshtastic_device_found(self):
        from btcmesh_client_gui import _friendly_connect_error
        from transport.base import TransportConnectionError

        result = _friendly_connect_error(
            '/dev/ttyUSB0', TransportConnectionError("No Meshtastic device found")
        )
        self.assertEqual(result, "No Meshtastic device found")

    def test_permission_denied(self):
        from btcmesh_client_gui import _friendly_connect_error
        from transport.base import TransportConnectionError

        result = _friendly_connect_error(
            '/dev/ttyUSB0', TransportConnectionError("Permission denied opening port")
        )
        self.assertEqual(result, "Permission denied accessing /dev/ttyUSB0")

    def test_could_not_open_port(self):
        from btcmesh_client_gui import _friendly_connect_error
        from transport.base import TransportConnectionError

        result = _friendly_connect_error(
            '/dev/ttyUSB0', TransportConnectionError("Failed to connect: could not open port")
        )
        self.assertEqual(result, "Could not open port /dev/ttyUSB0")

    def test_timeout_reframed_as_did_not_respond_not_connection_failure(self):
        """The wording change this fix is actually about: a timeout no
        longer reads as a failed connection attempt the user asked for."""
        from btcmesh_client_gui import _friendly_connect_error
        from transport.base import TransportConnectionError

        result = _friendly_connect_error(
            '/dev/ttyUSB0',
            TransportConnectionError("Failed to connect: Timed out waiting for connection completion"),
        )
        self.assertNotIn('waiting for connection completion', result)
        self.assertIn('did not respond', result)
        self.assertIn('/dev/ttyUSB0', result)

    def test_unrecognized_message_passed_through(self):
        """Given an error that doesn't match any known pattern, Then the
        original message is returned unchanged rather than losing detail."""
        from btcmesh_client_gui import _friendly_connect_error
        from transport.base import TransportConnectionError

        result = _friendly_connect_error(
            '/dev/ttyUSB0', TransportConnectionError("Something unusual happened")
        )
        self.assertEqual(result, "Something unusual happened")


# =============================================================================
# Story 11.3: Display Connected Device Name
# Tests for displaying the connected device's name in the connection status
# =============================================================================

class TestDisplayDeviceNameStory113(unittest.TestCase):
    """Tests for displaying connected device name - Story 11.3."""

    def _create_mock_node(self, node_id, long_name, short_name):
        """Helper to create a mock node structure."""
        return {
            'user': {
                'id': node_id,
                'longName': long_name,
                'shortName': short_name,
            },
        }

    def test_get_own_node_name_returns_long_name(self):
        """Given interface has own node with longName, Then returns longName."""
        from btcmesh_client_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': self._create_mock_node('!abcd1234', 'My Device', 'MYDEV'),
        }

        result = get_own_node_name(mock_iface)

        self.assertEqual(result, 'My Device')

    def test_get_own_node_name_returns_short_name_if_no_long_name(self):
        """Given interface has own node without longName, Then returns shortName."""
        from btcmesh_client_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': 'SHRT',
                },
            },
        }

        result = get_own_node_name(mock_iface)

        self.assertEqual(result, 'SHRT')

    def test_get_own_node_name_returns_none_if_no_name(self):
        """Given interface has own node without any name, Then returns None."""
        from btcmesh_client_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {
            '!abcd1234': {
                'user': {
                    'id': '!abcd1234',
                    'longName': '',
                    'shortName': '',
                },
            },
        }

        result = get_own_node_name(mock_iface)

        self.assertIsNone(result)

    def test_get_own_node_name_returns_none_if_no_interface(self):
        """Given no interface, Then returns None."""
        from btcmesh_client_gui import get_own_node_name

        result = get_own_node_name(None)

        self.assertIsNone(result)

    def test_get_own_node_name_returns_none_if_own_node_not_in_nodes(self):
        """Given own node not in nodes dict, Then returns None."""
        from btcmesh_client_gui import get_own_node_name
        mock_iface = unittest.mock.MagicMock()
        mock_iface.myInfo.my_node_num = 0xabcd1234
        mock_iface.nodes = {}

        result = get_own_node_name(mock_iface)

        self.assertIsNone(result)

    def test_connected_with_node_name_shows_name_in_status(self):
        """Given 'connected' with node_name, Then shows name in status."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', 'My Device')

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected - My Device (!abcd1234)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)

    def test_connected_without_node_name_shows_only_id(self):
        """Given 'connected' without node_name, Then shows only id."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', None)

        action = process_result(result)

        self.assertEqual(action.connection_text, 'Meshtastic: Connected (!abcd1234)')
        self.assertEqual(action.connection_color, COLOR_SUCCESS)

    def test_connected_log_message_includes_name(self):
        """Given 'connected' with node_name, Then log message includes name."""
        result = ('connected', unittest.mock.MagicMock(), '!abcd1234', 'My Device')

        action = process_result(result)

        self.assertIn('My Device', action.log_messages[0][0])
        self.assertIn('!abcd1234', action.log_messages[0][0])


# =============================================================================
# Story 9.5: Disable Controls During Transaction Send
# Tests for disabling input controls during sending and re-enabling on completion
# =============================================================================

class TestDisableControlsStory95(unittest.TestCase):
    """Tests for disabling controls during transaction send - Story 9.5.

    These tests verify:
    1. process_result() sets stop_sending correctly for different result types
    2. _handle_result() calls _set_controls_enabled(True) when stop_sending is True
    3. on_send_pressed() calls _set_controls_enabled(False) when starting to send
    """

    def test_handle_result_calls_set_controls_enabled_true_on_error(self):
        """Given 'error' result, Then _handle_result calls _set_controls_enabled(True)."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('error', 'Something failed'))

        gui._set_controls_enabled.assert_called_once_with(True)

    def test_handle_result_does_not_call_set_controls_enabled_on_log(self):
        """Given 'log' result, Then _handle_result does NOT call _set_controls_enabled."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui.is_sending = True
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.connection_label = unittest.mock.MagicMock()
        gui._show_success_popup = unittest.mock.MagicMock()

        btcmesh_client_gui.BTCMeshGUI._handle_result(gui, ('log', 'Progress', logging.INFO))

        gui._set_controls_enabled.assert_not_called()

    def test_on_send_pressed_calls_set_controls_enabled_false(self):
        """Given valid inputs, Then on_send_pressed calls _set_controls_enabled(False)."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui._get_own_node_id = unittest.mock.MagicMock(return_value='!12345678')
        gui.dest_input.text = '!abcd1234'
        gui.tx_input.text = 'aabbccdd'
        gui.dry_run_toggle.state = 'normal'
        gui.iface = unittest.mock.MagicMock()
        gui.send_btn = unittest.mock.MagicMock()
        gui.abort_btn = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui.result_queue = queue.Queue()
        gui.is_sending = False
        gui.abort_requested = False
        gui.selected_transport = "meshtastic"

        # Mock threading to prevent actual thread start
        with unittest.mock.patch('threading.Thread'):
            btcmesh_client_gui.BTCMeshGUI.on_send_pressed(gui, None)

        # Verify _set_controls_enabled was called with False
        gui._set_controls_enabled.assert_called_once_with(False)

    def test_on_send_pressed_does_not_call_set_controls_enabled_on_validation_error(self):
        """Given invalid inputs, Then on_send_pressed does NOT call _set_controls_enabled."""
        import btcmesh_client_gui

        gui = unittest.mock.MagicMock()
        gui._set_controls_enabled = unittest.mock.MagicMock()
        gui._get_own_node_id = unittest.mock.MagicMock(return_value='!12345678')
        gui.dest_input.text = ''  # Invalid: empty destination
        gui.tx_input.text = 'aabbccdd'
        gui.dry_run_toggle.state = 'normal'
        gui.iface = unittest.mock.MagicMock()
        gui.status_log = unittest.mock.MagicMock()
        gui._init_meshtastic = unittest.mock.MagicMock()

        btcmesh_client_gui.BTCMeshGUI.on_send_pressed(gui, None)

        # Verify _set_controls_enabled was NOT called (validation failed)
        gui._set_controls_enabled.assert_not_called()

    def test_process_result_stop_sending_true_for_completion_results(self):
        """Verify process_result sets stop_sending=True for completion results.

        ('cli_finished', ...), ('aborted',), and ('tx_success', ...) were
        dead result types (Issue 35) - removed from this list along with
        their process_result() branches. Completion via the current
        'send_result' type is covered separately (test_send_result_*)."""
        completion_results = [
            ('error', 'Failed'),
        ]

        for result in completion_results:
            action = process_result(result)
            self.assertTrue(action.stop_sending, f"stop_sending should be True for {result}")

    def test_process_result_stop_sending_false_for_progress_results(self):
        """Verify process_result sets stop_sending=False for progress results."""
        progress_results = [
            ('log', 'Progress', logging.INFO),
            ('connected', unittest.mock.MagicMock(), '!abc123'),
        ]

        for result in progress_results:
            action = process_result(result)
            self.assertFalse(action.stop_sending, f"stop_sending should be False for {result}")


if __name__ == '__main__':
    unittest.main()
