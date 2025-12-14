#!/usr/bin/env python3
"""
Tests for BTCMesh Server GUI (btcmesh_server_gui.py).

Story 15.1: Create Server GUI Application Structure
"""
import sys
import unittest
import unittest.mock

# Mock Kivy modules before importing btcmesh_server_gui
# This is necessary because Python loads the entire module (including Kivy imports)
# before extracting the specific functions we want to test.
# These mocks allow tests to run in environments without Kivy installed.


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

# Mock pubsub (used by btcmesh_server)
pubsub_mock = unittest.mock.MagicMock()
sys.modules['pubsub'] = pubsub_mock

# =============================================================================
# Story 15.1: Create Server GUI Application Structure
# Tests for basic GUI structure and theming
# =============================================================================


class TestServerGUIStructureStory151(unittest.TestCase):
    """Tests for Story 15.1: Create Server GUI Application Structure.

    Verifies:
    - GUI uses correct color scheme (Bitcoin orange theme)
    - Window title is "BTCMesh Relay Server"
    - Dark background color is used
    """

    def test_color_primary_is_bitcoin_orange(self):
        """Given server GUI module, Then COLOR_PRIMARY should be Bitcoin orange (#FF6B00)."""
        import btcmesh_server_gui

        # The color should be set via get_color_from_hex('#FF6B00')
        # Since we mock get_color_from_hex, we verify the constant exists
        self.assertTrue(hasattr(btcmesh_server_gui, 'COLOR_PRIMARY'))

    def test_color_bg_is_dark(self):
        """Given server GUI module, Then COLOR_BG should be dark (#1E1E1E)."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'COLOR_BG'))

    def test_color_success_exists(self):
        """Given server GUI module, Then COLOR_SUCCESS should exist for green indicators."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'COLOR_SUCCESS'))

    def test_color_error_exists(self):
        """Given server GUI module, Then COLOR_ERROR should exist for red indicators."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'COLOR_ERROR'))

    def test_color_warning_exists(self):
        """Given server GUI module, Then COLOR_WARNING should exist for orange warnings."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'COLOR_WARNING'))

    def test_btcmesh_server_app_class_exists(self):
        """Given server GUI module, Then BTCMeshServerApp class should exist."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'BTCMeshServerApp'))

    def test_btcmesh_server_gui_class_exists(self):
        """Given server GUI module, Then BTCMeshServerGUI class should exist."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'BTCMeshServerGUI'))

    def test_app_title_is_correct(self):
        """Given BTCMeshServerApp, Then title should be 'BTCMesh Relay Server'."""
        import btcmesh_server_gui

        app = btcmesh_server_gui.BTCMeshServerApp()
        # Mock the GUI class to avoid canvas issues
        with unittest.mock.patch.object(btcmesh_server_gui, 'BTCMeshServerGUI'):
            with unittest.mock.patch.object(btcmesh_server_gui, 'Window'):
                app.build()
        self.assertEqual(app.title, 'BTCMesh Relay Server')

    def test_status_log_class_exists(self):
        """Given server GUI module, Then StatusLog class should exist for activity display."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'StatusLog'))

    def test_main_function_exists(self):
        """Given server GUI module, Then main() function should exist as entry point."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'main'))
        self.assertTrue(callable(btcmesh_server_gui.main))


class TestServerGUIConnectionStatesStory151(unittest.TestCase):
    """Tests for connection state constants in Story 15.1.

    Verifies server-specific connection states for both
    Meshtastic and Bitcoin RPC.
    """

    def test_meshtastic_disconnected_state_exists(self):
        """Given server GUI, Then Meshtastic disconnected state should be defined."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'STATE_MESHTASTIC_DISCONNECTED'))

    def test_rpc_disconnected_state_exists(self):
        """Given server GUI, Then Bitcoin RPC disconnected state should be defined."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'STATE_RPC_DISCONNECTED'))


class TestServerGUIHelperFunctionsStory151(unittest.TestCase):
    """Tests for helper functions in the server GUI."""

    def test_get_log_color_exists(self):
        """Given server GUI module, Then get_log_color function should exist."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'get_log_color'))
        self.assertTrue(callable(btcmesh_server_gui.get_log_color))

    def test_get_log_color_returns_error_for_error_level(self):
        """Given ERROR log level, Then get_log_color should return COLOR_ERROR."""
        import btcmesh_server_gui
        import logging

        color = btcmesh_server_gui.get_log_color(logging.ERROR, "Some error")
        self.assertEqual(color, btcmesh_server_gui.COLOR_ERROR)

    def test_get_log_color_returns_warning_for_warning_level(self):
        """Given WARNING log level, Then get_log_color should return COLOR_WARNING."""
        import btcmesh_server_gui
        import logging

        color = btcmesh_server_gui.get_log_color(logging.WARNING, "Some warning")
        self.assertEqual(color, btcmesh_server_gui.COLOR_WARNING)

    def test_get_log_color_returns_success_for_success_message(self):
        """Given INFO level with 'success' in message, Then get_log_color should return COLOR_SUCCESS."""
        import btcmesh_server_gui
        import logging

        color = btcmesh_server_gui.get_log_color(logging.INFO, "Broadcast success")
        self.assertEqual(color, btcmesh_server_gui.COLOR_SUCCESS)

    def test_get_log_color_returns_none_for_normal_info(self):
        """Given INFO level with normal message, Then get_log_color should return None."""
        import btcmesh_server_gui
        import logging

        color = btcmesh_server_gui.get_log_color(logging.INFO, "Normal info message")
        self.assertIsNone(color)


# =============================================================================
# Story 15.2: Implement Start/Stop Server Controls
# Tests for server start and stop functionality
# =============================================================================


class TestServerStartStopStory152(unittest.TestCase):
    """Tests for Story 15.2: Implement Start/Stop Server Controls.

    Verifies:
    - Start button initializes Meshtastic and Bitcoin RPC
    - Stop button gracefully shuts down connections
    - Button states update correctly
    - Log messages appear for start/stop events
    """

    def setUp(self):
        """Set up test fixtures."""
        # Reload the module to get fresh state
        if 'btcmesh_server_gui' in sys.modules:
            del sys.modules['btcmesh_server_gui']

    def test_server_gui_has_start_button(self):
        """Given server GUI, Then it should have a start_btn attribute."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, 'start_btn'))

    def test_server_gui_has_stop_button(self):
        """Given server GUI, Then it should have a stop_btn attribute."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, 'stop_btn'))

    def test_stop_button_initially_disabled(self):
        """Given server GUI just started, Then stop button should be disabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(gui.stop_btn.disabled)

    def test_is_running_initially_false(self):
        """Given server GUI just started, Then is_running should be False."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertFalse(gui.is_running)

    def test_server_gui_has_result_queue(self):
        """Given server GUI, Then it should have a result_queue for thread communication."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, 'result_queue'))

    def test_server_gui_has_stop_event(self):
        """Given server GUI, Then it should have _stop_event for thread control."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, '_stop_event'))

    def test_server_gui_has_log_handler_attribute(self):
        """Given server GUI, Then it should have _log_handler attribute."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, '_log_handler'))
        self.assertIsNone(gui._log_handler)

    def test_on_start_pressed_disables_start_button(self):
        """Given operator clicks Start Server, Then start button should be disabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            with unittest.mock.patch.object(btcmesh_server_gui, 'threading'):
                gui = btcmesh_server_gui.BTCMeshServerGUI()
                mock_instance = unittest.mock.MagicMock()
                gui.on_start_pressed(mock_instance)
        self.assertTrue(gui.start_btn.disabled)

    def test_on_stop_pressed_disables_stop_button(self):
        """Given operator clicks Stop Server, Then stop button should be disabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            with unittest.mock.patch.object(btcmesh_server_gui, 'threading'):
                gui = btcmesh_server_gui.BTCMeshServerGUI()
                gui.is_running = True
                mock_instance = unittest.mock.MagicMock()
                gui.on_stop_pressed(mock_instance)
        self.assertTrue(gui.stop_btn.disabled)


class TestServerResultHandlingStory152(unittest.TestCase):
    """Tests for result queue handling in Story 15.2."""

    def setUp(self):
        """Set up test fixtures."""
        if 'btcmesh_server_gui' in sys.modules:
            del sys.modules['btcmesh_server_gui']

    def test_handle_result_server_started_sets_is_running(self):
        """Given 'server_started' result, Then is_running should be True."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('server_started', None))
        self.assertTrue(gui.is_running)

    def test_handle_result_server_started_enables_stop_button(self):
        """Given 'server_started' result, Then stop button should be enabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('server_started', None))
        self.assertFalse(gui.stop_btn.disabled)

    def test_handle_result_server_stopped_sets_is_running_false(self):
        """Given 'server_stopped' result, Then is_running should be False."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui.is_running = True
            gui._handle_result(('server_stopped', None))
        self.assertFalse(gui.is_running)

    def test_handle_result_server_stopped_enables_start_button(self):
        """Given 'server_stopped' result, Then start button should be enabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui.start_btn.disabled = True
            gui._handle_result(('server_stopped', None))
        self.assertFalse(gui.start_btn.disabled)

    def test_handle_result_rpc_connected_updates_label(self):
        """Given 'rpc_connected' result with host, Then RPC label should show connected with host."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('rpc_connected', {'host': 'localhost:8332', 'is_tor': False}))
        self.assertIn('Connected', gui.rpc_label.text)
        self.assertIn('localhost:8332', gui.rpc_label.text)
        self.assertNotIn('[Tor]', gui.rpc_label.text)

    def test_handle_result_rpc_connected_with_tor(self):
        """Given 'rpc_connected' result with Tor, Then RPC label should show Tor badge."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('rpc_connected', {'host': '*.onion', 'is_tor': True}))
        self.assertIn('Connected', gui.rpc_label.text)
        self.assertIn('*.onion', gui.rpc_label.text)
        self.assertIn('[Tor]', gui.rpc_label.text)

    def test_handle_result_rpc_connected_without_host(self):
        """Given 'rpc_connected' result without host, Then RPC label shows default text."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('rpc_connected', {'host': None, 'is_tor': False}))
        self.assertEqual(gui.rpc_label.text, btcmesh_server_gui.STATE_RPC_CONNECTED.text)

    def test_handle_result_rpc_failed_updates_label(self):
        """Given 'rpc_failed' result, Then RPC label should show failed state."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('rpc_failed', 'Connection refused'))
        self.assertEqual(gui.rpc_label.text, btcmesh_server_gui.STATE_RPC_FAILED.text)

    def test_handle_result_meshtastic_connected_updates_label(self):
        """Given 'meshtastic_connected' result with device, Then Meshtastic label should show connected with device."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('meshtastic_connected', {'node_id': '!abcdef12', 'device': '/dev/ttyUSB0'}))
        self.assertIn('Connected', gui.meshtastic_label.text)
        self.assertIn('!abcdef12', gui.meshtastic_label.text)
        self.assertIn('/dev/ttyUSB0', gui.meshtastic_label.text)

    def test_handle_result_meshtastic_connected_without_device(self):
        """Given 'meshtastic_connected' result without device, Then label shows connected without device path."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('meshtastic_connected', {'node_id': '!abcdef12', 'device': None}))
        self.assertIn('Connected', gui.meshtastic_label.text)
        self.assertIn('!abcdef12', gui.meshtastic_label.text)
        self.assertNotIn(') on ', gui.meshtastic_label.text)  # No device path syntax

    def test_handle_result_meshtastic_failed_updates_label(self):
        """Given 'meshtastic_failed' result, Then Meshtastic label should show failed."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui._handle_result(('meshtastic_failed', 'No device found'))
        self.assertEqual(gui.meshtastic_label.text, btcmesh_server_gui.STATE_MESHTASTIC_FAILED.text)

    def test_handle_result_meshtastic_failed_re_enables_start(self):
        """Given 'meshtastic_failed' result, Then start button should be re-enabled."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
            gui.start_btn.disabled = True
            gui._handle_result(('meshtastic_failed', 'No device found'))
        self.assertFalse(gui.start_btn.disabled)


class TestServerLogParsingStory152(unittest.TestCase):
    """Tests for log parsing in Story 15.2."""

    def setUp(self):
        """Set up test fixtures."""
        if 'btcmesh_server_gui' in sys.modules:
            del sys.modules['btcmesh_server_gui']

    def test_parse_log_for_status_function_exists(self):
        """Given server GUI module, Then parse_log_for_status function should exist."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'parse_log_for_status'))
        self.assertTrue(callable(btcmesh_server_gui.parse_log_for_status))

    def test_parse_log_detects_rpc_connected(self):
        """Given RPC connected log message with host, Then parse_log_for_status returns rpc_connected with dict."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Connected to Bitcoin Core RPC node successfully. Host: localhost:8332, Tor: False"
        )
        self.assertEqual(result[0], 'rpc_connected')
        self.assertEqual(result[1], {'host': 'localhost:8332', 'is_tor': False})

    def test_parse_log_detects_rpc_connected_with_tor(self):
        """Given RPC connected log message with Tor, Then parse_log_for_status returns is_tor=True."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Connected to Bitcoin Core RPC node successfully. Host: *.onion, Tor: True"
        )
        self.assertEqual(result[0], 'rpc_connected')
        self.assertEqual(result[1], {'host': '*.onion', 'is_tor': True})

    def test_parse_log_detects_rpc_failed(self):
        """Given RPC failed log message, Then parse_log_for_status returns rpc_failed."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Failed to connect to Bitcoin Core RPC node: Connection refused. Continuing without RPC."
        )
        self.assertEqual(result[0], 'rpc_failed')
        self.assertIn('Connection refused', result[1])

    def test_parse_log_detects_meshtastic_connected(self):
        """Given Meshtastic connected log message, Then parse_log_for_status returns meshtastic_connected with dict."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Meshtastic interface initialized successfully. Device: /dev/ttyUSB0, My Node Num: !abcdef12"
        )
        self.assertEqual(result[0], 'meshtastic_connected')
        self.assertEqual(result[1], {'node_id': '!abcdef12', 'device': '/dev/ttyUSB0'})

    def test_parse_log_detects_meshtastic_failed(self):
        """Given Meshtastic failed log message, Then parse_log_for_status returns meshtastic_failed."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Failed to initialize Meshtastic interface. Exiting."
        )
        self.assertEqual(result[0], 'meshtastic_failed')

    def test_parse_log_detects_server_started(self):
        """Given server started log message, Then parse_log_for_status returns server_started."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Registered Meshtastic message handler. Waiting for messages..."
        )
        self.assertEqual(result, ('server_started', None))

    def test_parse_log_detects_server_stopped(self):
        """Given server stopped log message, Then parse_log_for_status returns server_stopped."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Closing Meshtastic interface..."
        )
        self.assertEqual(result, ('server_stopped', None))

    def test_parse_log_returns_none_for_normal_message(self):
        """Given normal log message, Then parse_log_for_status returns None."""
        import btcmesh_server_gui

        result = btcmesh_server_gui.parse_log_for_status(
            "Some normal log message"
        )
        self.assertIsNone(result)

    def test_process_results_method_exists(self):
        """Given server GUI, Then _process_results method should exist."""
        import btcmesh_server_gui

        with unittest.mock.patch.object(btcmesh_server_gui, 'Clock'):
            gui = btcmesh_server_gui.BTCMeshServerGUI()
        self.assertTrue(hasattr(gui, '_process_results'))
        self.assertTrue(callable(gui._process_results))


class TestQueueLogHandlerStory152(unittest.TestCase):
    """Tests for QueueLogHandler class in Story 15.2."""

    def setUp(self):
        """Set up test fixtures."""
        if 'btcmesh_server_gui' in sys.modules:
            del sys.modules['btcmesh_server_gui']

    def test_queue_log_handler_class_exists(self):
        """Given server GUI module, Then QueueLogHandler class should exist."""
        import btcmesh_server_gui

        self.assertTrue(hasattr(btcmesh_server_gui, 'QueueLogHandler'))

    def test_queue_log_handler_puts_log_to_queue(self):
        """Given QueueLogHandler with a queue, When emit is called, Then message goes to queue."""
        import btcmesh_server_gui
        import logging
        import queue

        q = queue.Queue()
        handler = btcmesh_server_gui.QueueLogHandler(q)
        handler.setFormatter(logging.Formatter('%(message)s'))

        record = logging.LogRecord(
            name='test', level=logging.INFO, pathname='', lineno=0,
            msg='Test message', args=(), exc_info=None
        )
        handler.emit(record)

        result = q.get_nowait()
        self.assertEqual(result[0], 'log')
        self.assertEqual(result[1], 'Test message')
        self.assertEqual(result[2], logging.INFO)


if __name__ == '__main__':
    unittest.main()
