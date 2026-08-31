#!/usr/bin/env python3
"""
Tests for BTCMesh GUI Common Components (gui_common.py).

Tests shared UI components, color constants, and helper functions
used by both client and server GUIs.
"""
import sys
import unittest
import unittest.mock
import logging


# Mock Kivy modules before importing gui_common
# This allows tests to run in environments without Kivy installed.

class MockCanvas:
    """Mock canvas for Kivy widgets - acts as context manager."""
    def __init__(self):
        self.before = self  # self-referential for canvas.before

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockBoxLayout:
    """Mock base class for BoxLayout."""
    def __init__(self, **kwargs):
        self.canvas = MockCanvas()
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = 100
        self.height = kwargs.get('height', 100)
        self.children = []

    def add_widget(self, widget):
        widget.parent = self
        self.children.append(widget)

    def remove_widget(self, widget):
        widget.parent = None
        if widget in self.children:
            self.children.remove(widget)

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
        self.height = kwargs.get('height', 100)
        self.children = []

    def add_widget(self, widget):
        widget.parent = self
        self.children.append(widget)

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockWidget:
    """Mock base class for Widget."""
    def __init__(self, **kwargs):
        self.size = (100, 100)
        self.pos = (0, 0)
        self.width = kwargs.get('width', 100)
        self.height = kwargs.get('height', 100)
        self.size_hint_x = kwargs.get('size_hint_x', 1)
        self.size_hint_y = kwargs.get('size_hint_y', 1)
        self.canvas = MockCanvas()

    def bind(self, **kwargs):
        pass


kivy_mock = unittest.mock.MagicMock()
# get_color_from_hex should return a tuple like (r, g, b, a)
kivy_mock.get_color_from_hex = lambda hex_str: (1.0, 0.42, 0.0, 1.0)  # Return consistent tuple

boxlayout_mock = unittest.mock.MagicMock()
boxlayout_mock.BoxLayout = MockBoxLayout

scrollview_mock = unittest.mock.MagicMock()
scrollview_mock.ScrollView = MockScrollView

widget_mock = unittest.mock.MagicMock()
widget_mock.Widget = MockWidget


class MockTextInput:
    """Mock base class for TextInput that properly stores password attribute."""
    def __init__(self, **kwargs):
        self.text = kwargs.get('text', '')
        self.hint_text = kwargs.get('hint_text', '')
        self.password = kwargs.get('password', False)
        self.multiline = kwargs.get('multiline', True)
        self.size_hint_x = kwargs.get('size_hint_x', 1)
        self.background_color = kwargs.get('background_color', (1, 1, 1, 1))
        self.foreground_color = kwargs.get('foreground_color', (0, 0, 0, 1))
        self.cursor_color = kwargs.get('cursor_color', (0, 0, 0, 1))
        self.input_filter = kwargs.get('input_filter', None)

    def bind(self, **kwargs):
        pass


class MockLabel:
    """Mock base class for Label that properly stores text and parent."""
    def __init__(self, **kwargs):
        self.text = kwargs.get('text', '')
        self.color = kwargs.get('color', (1, 1, 1, 1))
        self.size_hint_y = kwargs.get('size_hint_y', 1)
        self.size_hint_x = kwargs.get('size_hint_x', 1)
        self.height = kwargs.get('height', 20)
        self.width = kwargs.get('width', 100)
        self.halign = kwargs.get('halign', 'left')
        self.valign = kwargs.get('valign', 'middle')
        self.parent = None
        self.texture_size = (100, 20)
        self.text_size = (None, None)
        self.size = (100, 20)
        self.bold = kwargs.get('bold', False)

    def bind(self, **kwargs):
        pass

    def setter(self, prop):
        """Mock setter method for property binding."""
        return lambda *args: None


class MockButton:
    """Mock base class for Button that properly stores text attribute."""
    def __init__(self, **kwargs):
        self.text = kwargs.get('text', '')
        self.size_hint_x = kwargs.get('size_hint_x', 1)
        self.size_hint_y = kwargs.get('size_hint_y', 1)
        self.width = kwargs.get('width', 100)
        self.height = kwargs.get('height', 100)
        self.background_color = kwargs.get('background_color', (1, 1, 1, 1))
        self.background_normal = kwargs.get('background_normal', '')
        self.font_size = kwargs.get('font_size', '14sp')
        self.bold = kwargs.get('bold', False)
        self.disabled = kwargs.get('disabled', False)

    def bind(self, **kwargs):
        pass


textinput_mock = unittest.mock.MagicMock()
textinput_mock.TextInput = MockTextInput

button_mock = unittest.mock.MagicMock()
button_mock.Button = MockButton

label_mock = unittest.mock.MagicMock()
label_mock.Label = MockLabel

sys.modules['kivy'] = kivy_mock
sys.modules['kivy.uix'] = kivy_mock
sys.modules['kivy.uix.boxlayout'] = boxlayout_mock
sys.modules['kivy.uix.widget'] = widget_mock
sys.modules['kivy.uix.label'] = label_mock
sys.modules['kivy.uix.button'] = button_mock
sys.modules['kivy.uix.textinput'] = textinput_mock
sys.modules['kivy.uix.scrollview'] = scrollview_mock
sys.modules['kivy.graphics'] = kivy_mock
sys.modules['kivy.clock'] = kivy_mock
sys.modules['kivy.core'] = kivy_mock
sys.modules['kivy.core.window'] = kivy_mock
sys.modules['kivy.utils'] = kivy_mock


# =============================================================================
# Tests for Color Constants
# =============================================================================

class TestColorConstants(unittest.TestCase):
    """Tests for color constants defined in gui_common."""

    def test_color_primary_exists(self):
        """Given gui_common module, Then COLOR_PRIMARY should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_PRIMARY'))

    def test_color_success_exists(self):
        """Given gui_common module, Then COLOR_SUCCESS should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_SUCCESS'))

    def test_color_error_exists(self):
        """Given gui_common module, Then COLOR_ERROR should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_ERROR'))

    def test_color_warning_exists(self):
        """Given gui_common module, Then COLOR_WARNING should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_WARNING'))

    def test_color_bg_exists(self):
        """Given gui_common module, Then COLOR_BG should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_BG'))

    def test_color_bg_light_exists(self):
        """Given gui_common module, Then COLOR_BG_LIGHT should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_BG_LIGHT'))

    def test_color_secundary_exists(self):
        """Given gui_common module, Then COLOR_SECONDARY should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_SECONDARY'))

    def test_color_disconnected_exists(self):
        """Given gui_common module, Then COLOR_DISCONNECTED should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'COLOR_DISCONNECTED'))

    def test_color_disconnected_is_gray(self):
        """Given COLOR_DISCONNECTED, Then it should be a gray color tuple."""
        from gui import gui_common
        self.assertEqual(gui_common.COLOR_DISCONNECTED, (0.7, 0.7, 0.7, 1))


# =============================================================================
# Tests for ConnectionState Dataclass
# =============================================================================

class TestConnectionState(unittest.TestCase):
    """Tests for ConnectionState dataclass."""

    def test_connection_state_exists(self):
        """Given gui_common module, Then ConnectionState should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'ConnectionState'))

    def test_connection_state_has_text_attribute(self):
        """Given ConnectionState, Then it should have a text attribute."""
        from gui import gui_common
        state = gui_common.ConnectionState(text='Test', color=(1, 1, 1, 1))
        self.assertEqual(state.text, 'Test')

    def test_connection_state_has_color_attribute(self):
        """Given ConnectionState, Then it should have a color attribute."""
        from gui import gui_common
        state = gui_common.ConnectionState(text='Test', color=(0.5, 0.5, 0.5, 1))
        self.assertEqual(state.color, (0.5, 0.5, 0.5, 1))

    def test_connection_state_is_frozen(self):
        """Given ConnectionState, Then it should be immutable (frozen)."""
        from gui import gui_common
        state = gui_common.ConnectionState(text='Test', color=(1, 1, 1, 1))
        with self.assertRaises(AttributeError):
            state.text = 'New Text'


# =============================================================================
# Tests for get_log_color Function
# =============================================================================

class TestGetLogColor(unittest.TestCase):
    """Tests for get_log_color helper function."""

    def test_get_log_color_exists(self):
        """Given gui_common module, Then get_log_color should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'get_log_color'))
        self.assertTrue(callable(gui_common.get_log_color))

    def test_get_log_color_returns_error_for_error_level(self):
        """Given ERROR log level, Then get_log_color should return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.ERROR, "Some error")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_critical_level(self):
        """Given CRITICAL log level, Then get_log_color should return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.CRITICAL, "Critical error")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_warning_for_warning_level(self):
        """Given WARNING log level, Then get_log_color should return COLOR_WARNING."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.WARNING, "Some warning")
        self.assertEqual(color, gui_common.COLOR_WARNING)

    def test_get_log_color_returns_success_for_success_keyword(self):
        """Given INFO level with 'success' in message, Then return COLOR_SUCCESS."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Operation success")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_log_color_returns_success_for_txid_keyword(self):
        """Given INFO level with 'txid:' in message, Then return COLOR_SUCCESS."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Broadcast success. TXID: abc123")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_log_color_returns_success_for_successfully_keyword(self):
        """Given INFO level with 'successfully' in message, Then return COLOR_SUCCESS."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Connected successfully")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_log_color_returns_error_for_failed_keyword_at_info(self):
        """Given INFO level with 'failed' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Broadcast failed: some error")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_nack_keyword_at_info(self):
        """Given INFO level with 'nack' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Sending NACK to client")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_timeout_keyword_at_info(self):
        """Given INFO level with 'timed out' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Session timed out. Sending NACK")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_closing_keyword_at_info(self):
        """Given INFO level with 'closing' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Closing Meshtastic interface...")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_cannot_keyword_at_info(self):
        """Given INFO level with 'cannot' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Cannot send reply: no interface")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_error_for_abort_keyword_at_info(self):
        """Given INFO level with 'abort' in message, Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Session aborted by sender")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_error_keywords_take_priority_over_success(self):
        """Given message with both error and success keywords, Then error takes priority."""
        from gui import gui_common
        # 'failed' is error keyword, 'success' would be success keyword
        color = gui_common.get_log_color(logging.INFO, "Success check failed")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_with_custom_error_keywords(self):
        """Given custom error keywords, Then use those for matching."""
        from gui import gui_common
        color = gui_common.get_log_color(
            logging.INFO, "Connection dropped",
            error_keywords=['dropped']
        )
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_log_color_returns_none_for_normal_info(self):
        """Given INFO level with normal message, Then return None."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "Normal info message")
        self.assertIsNone(color)

    def test_get_log_color_with_custom_success_keywords(self):
        """Given custom success keywords, Then use those for matching."""
        from gui import gui_common
        # Default keywords don't include 'complete'
        color = gui_common.get_log_color(logging.INFO, "Task complete", success_keywords=['complete'])
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_log_color_case_insensitive(self):
        """Given message with mixed case, Then matching should be case-insensitive."""
        from gui import gui_common
        color = gui_common.get_log_color(logging.INFO, "SUCCESS message")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)


# =============================================================================
# Tests for get_print_color Function
# =============================================================================

class TestGetPrintColor(unittest.TestCase):
    """Tests for get_print_color helper function."""

    def test_get_print_color_exists(self):
        """Given gui_common module, Then get_print_color should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'get_print_color'))
        self.assertTrue(callable(gui_common.get_print_color))

    def test_get_print_color_returns_error_for_error_keyword(self):
        """Given message with 'error', Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_print_color("Error occurred")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_print_color_returns_error_for_failed_keyword(self):
        """Given message with 'failed', Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_print_color("Connection failed")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_print_color_returns_error_for_abort_keyword(self):
        """Given message with 'abort', Then return COLOR_ERROR."""
        from gui import gui_common
        color = gui_common.get_print_color("User abort")
        self.assertEqual(color, gui_common.COLOR_ERROR)

    def test_get_print_color_returns_success_for_success_keyword(self):
        """Given message with 'success', Then return COLOR_SUCCESS."""
        from gui import gui_common
        color = gui_common.get_print_color("Operation success")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_print_color_returns_success_for_txid_keyword(self):
        """Given message with 'txid', Then return COLOR_SUCCESS."""
        from gui import gui_common
        color = gui_common.get_print_color("TXID: abc123def456")
        self.assertEqual(color, gui_common.COLOR_SUCCESS)

    def test_get_print_color_returns_none_for_normal_message(self):
        """Given normal message, Then return None."""
        from gui import gui_common
        color = gui_common.get_print_color("Normal message")
        self.assertIsNone(color)


# =============================================================================
# Tests for StatusLog Class
# =============================================================================

class TestStatusLog(unittest.TestCase):
    """Tests for StatusLog widget class."""

    def test_status_log_class_exists(self):
        """Given gui_common module, Then StatusLog class should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'StatusLog'))


class TestBusyIndicator(unittest.TestCase):
    """Tests for BusyIndicator (Issue 39) - a purely-visual, reference-
    counted busy state for a trigger button. It cycles the button's own
    text and disables it (only to prevent a duplicate concurrent trigger
    of the *same* operation - never any other widget). Reference
    counting (not a boolean) is the whole point of this design:
    independent, possibly-overlapping code paths each get their own
    paired start()/stop() call without one path's stop() restoring idle
    state while another path's work is still in flight (see
    project/plans/story_29_1.md's Key Design Decisions)."""

    def _button(self):
        return unittest.mock.MagicMock(text='', disabled=False)

    def test_sets_idle_text_on_construction(self):
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        self.assertFalse(indicator.active)
        self.assertEqual(button.text, "Scan")
        self.assertFalse(button.disabled)

    def test_start_makes_it_active_sets_text_and_disables_button(self):
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.start("Scanning devices...")
        self.assertTrue(indicator.active)
        self.assertEqual(button.text, "Scanning devices...")
        self.assertTrue(button.disabled)

    def test_stop_after_single_start_restores_idle_state(self):
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.start("Scanning devices...")
        indicator.stop()
        self.assertFalse(indicator.active)
        self.assertEqual(button.text, "Scan")
        self.assertFalse(button.disabled)

    def test_reference_counted_two_starts_need_two_stops(self):
        """The core requirement this widget exists to satisfy: two
        independent reasons to be busy overlapping must not let the
        first stop() restore idle state while the second reason is
        still in flight."""
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.start("First...")
        indicator.start("Second...")
        indicator.stop()
        self.assertTrue(indicator.active, "should still be busy - one start() is unmatched")
        self.assertTrue(button.disabled)
        indicator.stop()
        self.assertFalse(indicator.active)
        self.assertEqual(button.text, "Scan")
        self.assertFalse(button.disabled)

    def test_extra_stop_without_matching_start_is_a_no_op(self):
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.stop()  # no matching start() - must not raise or go negative
        self.assertFalse(indicator.active)
        indicator.start("Busy...")
        indicator.stop()
        indicator.stop()  # extra stop after already balanced
        self.assertFalse(indicator.active)
        self.assertEqual(button.text, "Scan")

    def test_second_start_does_not_reset_the_displayed_message(self):
        """Only the first start() in an overlapping pair sets the
        message - a second, concurrent start() shouldn't change what's
        already showing."""
        from gui.gui_common import BusyIndicator
        button = self._button()
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.start("First...")
        indicator.start("Second...")
        self.assertEqual(button.text, "First...")

    def test_never_touches_any_other_widget(self):
        """Only the button passed to the constructor is ever mutated -
        this is the whole point vs. disabling e.g. a device dropdown."""
        from gui.gui_common import BusyIndicator
        button = self._button()
        other_widget = unittest.mock.MagicMock(disabled=False)
        indicator = BusyIndicator(button, idle_text="Scan")
        indicator.start("Busy...")
        indicator.stop()
        self.assertFalse(other_widget.disabled)


# =============================================================================
# Tests for Widget Factory Functions
# =============================================================================

class TestWidgetFactories(unittest.TestCase):
    """Tests for widget factory functions."""

    def test_create_separator_exists(self):
        """Given gui_common module, Then create_separator should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_separator'))
        self.assertTrue(callable(gui_common.create_separator))

    def test_create_title_exists(self):
        """Given gui_common module, Then create_title should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_title'))
        self.assertTrue(callable(gui_common.create_title))

    def test_create_section_label_exists(self):
        """Given gui_common module, Then create_section_label should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_section_label'))
        self.assertTrue(callable(gui_common.create_section_label))

    def test_create_clear_button_exists(self):
        """Given gui_common module, Then create_clear_button should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_clear_button'))
        self.assertTrue(callable(gui_common.create_clear_button))

    def test_create_action_button_exists(self):
        """Given gui_common module, Then create_action_button should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_action_button'))
        self.assertTrue(callable(gui_common.create_action_button))

    def test_create_status_row_exists(self):
        """Given gui_common module, Then create_status_row should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_status_row'))
        self.assertTrue(callable(gui_common.create_status_row))

    def test_create_status_row_returns_tuple(self):
        """Given create_status_row call, Then returns tuple of (BoxLayout, Label)."""
        from gui import gui_common
        result = gui_common.create_status_row('Test:', 'Value')
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_create_status_row_returns_label_as_second_element(self):
        """Given create_status_row call, Then second element is a Label-like object."""
        from gui import gui_common
        _, value_label = gui_common.create_status_row('Label:', 'Initial Value')
        # The value_label should be a Label (mocked in tests)
        # We can verify it has expected Label attributes
        self.assertTrue(hasattr(value_label, 'text'))
        self.assertTrue(hasattr(value_label, 'color'))

    def test_create_toggle_button_exists(self):
        """Given gui_common module, Then create_toggle_button should be defined."""
        from gui import gui_common
        self.assertTrue(hasattr(gui_common, 'create_toggle_button'))
        self.assertTrue(callable(gui_common.create_toggle_button))

    def test_create_toggle_button_returns_button(self):
        """Given create_toggle_button call, Then returns a Button-like object."""
        from gui import gui_common
        btn = gui_common.create_toggle_button('Show')
        self.assertTrue(hasattr(btn, 'text'))

    def test_create_toggle_button_uses_provided_text(self):
        """Given create_toggle_button call with text, Then button text is set correctly."""
        from gui import gui_common
        btn = gui_common.create_toggle_button('Toggle')
        self.assertEqual(btn.text, 'Toggle')


# =============================================================================
# Device Selection Helpers - shared between client and server GUIs
# (Story 27.2/27.3; see project/plans/story_27_1.md's "Architecture
# Revision" section for the design)
# =============================================================================

class _ImmediateThread:
    """Runs the thread target synchronously so tests stay deterministic,
    without real background threads."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


def _drain(q):
    results = []
    while not q.empty():
        results.append(q.get_nowait())
    return results


class TestProbeDevicesInBackground(unittest.TestCase):
    """Tests for probe_devices_in_background()."""

    def tearDown(self):
        """_probing_paths is module-level, shared-state (Issue 61) -
        clear it so a test that errors mid-probe can't leak a path into
        the next test."""
        from gui import gui_common
        gui_common._probing_paths.clear()

    def test_pushes_one_result_per_device(self):
        """Given a list of devices, Then probe_device_identity() is called
        for each, a device_identity result is pushed per device, and a
        final device_probe_complete sentinel is pushed once the whole
        batch is done (Issue 39 - the only reliable "all done" signal a
        caller has, e.g. to stop a busy indicator)."""
        import queue
        from gui import gui_common
        from core.meshtastic_utils import ProbedDevice

        result_queue = queue.Queue()
        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 side_effect=[
                     ProbedDevice(node_id='!11111111', name='Node One'),
                     ProbedDevice(node_id=None, name=None),
                 ],
             ):
            gui_common.probe_devices_in_background(devices, result_queue)

        self.assertEqual(
            _drain(result_queue),
            [
                ('device_identity', '/dev/ttyUSB0', '!11111111', 'Node One', None, None),
                ('device_identity', '/dev/ttyACM0', None, None, None, None),
                ('device_probe_complete',),
            ],
        )

    def test_skip_paths_are_not_probed(self):
        """Given a path in skip_paths, Then it's not probed and no result
        is pushed for it (the completion sentinel still fires)."""
        import queue
        from gui import gui_common
        from core.meshtastic_utils import ProbedDevice

        result_queue = queue.Queue()
        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 return_value=ProbedDevice(node_id='!22222222', name='Node Two'),
             ) as mock_probe:
            gui_common.probe_devices_in_background(
                devices, result_queue, skip_paths=frozenset({'/dev/ttyUSB0'})
            )

        mock_probe.assert_called_once_with('/dev/ttyACM0')
        self.assertEqual(
            _drain(result_queue),
            [
                ('device_identity', '/dev/ttyACM0', '!22222222', 'Node Two', None, None),
                ('device_probe_complete',),
            ],
        )

    def test_completion_sentinel_fires_even_if_a_probe_raises(self):
        """Issue 39: device_probe_complete must fire even when
        probe_device_identity() raises partway through the batch - a
        busy indicator's stop() call depends on it always arriving."""
        import queue
        from gui import gui_common

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 side_effect=RuntimeError("serial error"),
             ):
            with self.assertRaises(RuntimeError):
                gui_common.probe_devices_in_background(devices, result_queue)

        self.assertEqual(_drain(result_queue), [('device_probe_complete',)])

    def test_default_dispatches_to_meshtastic_probe(self):
        """Given transport_name is omitted, Then probe_meshtastic_device_identity()
        is used (Story 30.4 - default stays "meshtastic", zero behavior
        change for existing callers)."""
        import queue
        from gui import gui_common
        from core.device_scan import ProbedDevice

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 return_value=ProbedDevice(node_id='!11111111', name='Node One'),
             ) as mock_meshtastic_probe, \
             unittest.mock.patch('gui.gui_common.probe_meshcore_device_identity') as mock_meshcore_probe:
            gui_common.probe_devices_in_background(devices, result_queue)

        mock_meshtastic_probe.assert_called_once_with('/dev/ttyUSB0')
        mock_meshcore_probe.assert_not_called()

    def test_meshcore_transport_name_dispatches_to_meshcore_probe(self):
        """Given transport_name="meshcore", Then probe_meshcore_device_identity()
        is used instead of the Meshtastic one (Story 30.4)."""
        import queue
        from gui import gui_common
        from core.device_scan import ProbedDevice

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch('gui.gui_common.probe_meshtastic_device_identity') as mock_meshtastic_probe, \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshcore_device_identity',
                 return_value=ProbedDevice(node_id='a1b2c3d4e5f6', name='MC Node'),
             ) as mock_meshcore_probe:
            gui_common.probe_devices_in_background(devices, result_queue, transport_name='meshcore')

        mock_meshcore_probe.assert_called_once_with('/dev/ttyUSB0')
        mock_meshtastic_probe.assert_not_called()
        self.assertEqual(
            _drain(result_queue),
            [
                ('device_identity', '/dev/ttyUSB0', 'a1b2c3d4e5f6', 'MC Node', None, None),
                ('device_probe_complete',),
            ],
        )

    def test_should_abort_true_from_the_start_probes_nothing(self):
        """Story 30.4: given should_abort() is already True before the
        first device, Then no probe is attempted at all, but
        device_probe_complete still fires - a caller's busy-indicator
        start()/stop() pairing (ref-counted, Issue 39) must stay balanced
        even on an immediately-stale batch (e.g. the operator flipped the
        transport selector again before this batch's own thread even got
        scheduled)."""
        import queue
        from gui import gui_common

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch('gui.gui_common.probe_meshtastic_device_identity') as mock_probe:
            gui_common.probe_devices_in_background(
                devices, result_queue, should_abort=lambda: True
            )

        mock_probe.assert_not_called()
        self.assertEqual(_drain(result_queue), [('device_probe_complete',)])

    def test_should_abort_mid_batch_stops_remaining_devices(self):
        """Story 30.4: given should_abort() flips to True after the first
        device, Then the second device is never probed, but the first
        device's already-fetched result and the completion sentinel both
        still arrive - mirrors an operator switching transports while a
        multi-device probe batch is partway through."""
        import queue
        from gui import gui_common
        from core.device_scan import ProbedDevice

        result_queue = queue.Queue()
        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]
        abort_after_first = iter([False, True])

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 return_value=ProbedDevice(node_id='!11111111', name='Node One'),
             ) as mock_probe:
            gui_common.probe_devices_in_background(
                devices, result_queue, should_abort=lambda: next(abort_after_first)
            )

        mock_probe.assert_called_once_with('/dev/ttyUSB0')
        self.assertEqual(
            _drain(result_queue),
            [
                ('device_identity', '/dev/ttyUSB0', '!11111111', 'Node One', None, None),
                ('device_probe_complete',),
            ],
        )

    def test_skips_path_already_being_probed_by_another_batch(self):
        """Issue 61: given a path already registered in _probing_paths
        (an older, still-in-flight batch is mid-probe on it -
        should_abort only stops a batch from *starting* a new probe, not
        from finishing one already running), Then this batch skips it
        without probing and without a result, but the completion
        sentinel still fires - prevents two overlapping batches from
        opening concurrent connections to the same physical serial port
        (confirmed real-hardware to cause "could not open port"
        failures and orphaned per-connection background tasks)."""
        import queue
        from gui import gui_common
        from core.device_scan import ProbedDevice

        result_queue = queue.Queue()
        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]
        gui_common._probing_paths.add('/dev/ttyUSB0')

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 return_value=ProbedDevice(node_id='!22222222', name='Node Two'),
             ) as mock_probe:
            gui_common.probe_devices_in_background(devices, result_queue)

        mock_probe.assert_called_once_with('/dev/ttyACM0')
        self.assertEqual(
            _drain(result_queue),
            [
                ('device_identity', '/dev/ttyACM0', '!22222222', 'Node Two', None, None),
                ('device_probe_complete',),
            ],
        )

    def test_releases_path_after_probe_completes(self):
        """Given a path this batch just finished probing, Then it's
        removed from _probing_paths afterward - a later batch must be
        able to probe it again (e.g. a fresh rescan)."""
        import queue
        from gui import gui_common
        from core.device_scan import ProbedDevice

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 return_value=ProbedDevice(node_id='!11111111', name='Node One'),
             ):
            gui_common.probe_devices_in_background(devices, result_queue)

        self.assertNotIn('/dev/ttyUSB0', gui_common._probing_paths)

    def test_releases_path_even_when_probe_raises(self):
        """Given probe_device_identity() raises, Then the path is still
        released from _probing_paths (finally, not just the happy path) -
        otherwise one bad probe would permanently block that device from
        ever being probed again."""
        import queue
        from gui import gui_common

        result_queue = queue.Queue()
        devices = [{'path': '/dev/ttyUSB0', 'node_id': None, 'name': None}]

        with unittest.mock.patch('gui.gui_common.threading.Thread', _ImmediateThread), \
             unittest.mock.patch(
                 'gui.gui_common.probe_meshtastic_device_identity',
                 side_effect=RuntimeError("boom"),
             ):
            with self.assertRaises(RuntimeError):
                gui_common.probe_devices_in_background(devices, result_queue)

        self.assertNotIn('/dev/ttyUSB0', gui_common._probing_paths)


class TestDedupeDevicesByNodeId(unittest.TestCase):
    """Tests for dedupe_devices_by_node_id()."""

    def test_removes_earlier_duplicate_no_protection(self):
        """Given two paths sharing a node ID and no protect_path, Then the
        earlier-resolved one is dropped and keep_path survives."""
        from gui import gui_common

        devices = [
            {'path': '/dev/cu.SLAB_USBtoUART', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
            {'path': '/dev/cu.usbserial-0001', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
        ]

        new_devices, removed = gui_common.dedupe_devices_by_node_id(
            devices, keep_path='/dev/cu.usbserial-0001'
        )

        self.assertEqual(len(new_devices), 1)
        self.assertEqual(new_devices[0]['path'], '/dev/cu.usbserial-0001')
        self.assertEqual(removed['path'], '/dev/cu.SLAB_USBtoUART')

    def test_protect_path_survives_even_if_it_is_the_duplicate(self):
        """Given protect_path is the duplicate side (it resolved first;
        keep_path resolved to the same node ID second), Then keep_path is
        dropped instead - protect_path is never removed."""
        from gui import gui_common

        devices = [
            {'path': '/dev/cu.SLAB_USBtoUART', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
            {'path': '/dev/cu.usbserial-0001', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
        ]

        new_devices, removed = gui_common.dedupe_devices_by_node_id(
            devices,
            keep_path='/dev/cu.usbserial-0001',
            protect_path='/dev/cu.SLAB_USBtoUART',
        )

        self.assertEqual(len(new_devices), 1)
        self.assertEqual(new_devices[0]['path'], '/dev/cu.SLAB_USBtoUART')
        self.assertEqual(removed['path'], '/dev/cu.usbserial-0001')

    def test_protect_path_none_disables_exemption(self):
        """Given protect_path=None (the default), Then no device is ever
        protected - dedup behaves as if no active/protected device exists
        (the server GUI's case, which has no live-connection concept)."""
        from gui import gui_common

        devices = [
            {'path': '/dev/cu.SLAB_USBtoUART', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
            {'path': '/dev/cu.usbserial-0001', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
        ]

        new_devices, removed = gui_common.dedupe_devices_by_node_id(
            devices, keep_path='/dev/cu.usbserial-0001', protect_path=None
        )

        self.assertEqual(len(new_devices), 1)
        self.assertEqual(new_devices[0]['path'], '/dev/cu.usbserial-0001')

    def test_no_op_when_no_duplicate(self):
        """Given no other device shares keep_path's node ID, Then nothing
        is removed and removed is None."""
        from gui import gui_common

        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': 'One'},
            {'path': '/dev/ttyACM0', 'node_id': '!22222222', 'name': 'Two'},
        ]

        new_devices, removed = gui_common.dedupe_devices_by_node_id(devices, keep_path='/dev/ttyUSB0')

        self.assertEqual(len(new_devices), 2)
        self.assertIsNone(removed)

    def test_no_op_when_keep_path_node_id_is_none(self):
        """Given keep_path's own node_id is None (a failed probe), Then
        nothing is removed - there's nothing to dedupe against."""
        from gui import gui_common

        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': None, 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': None, 'name': None},
        ]

        new_devices, removed = gui_common.dedupe_devices_by_node_id(devices, keep_path='/dev/ttyUSB0')

        self.assertEqual(len(new_devices), 2)
        self.assertIsNone(removed)

    def test_does_not_mutate_input_list(self):
        """Given a devices list, Then the original list object is left
        untouched - callers must use the returned list."""
        from gui import gui_common

        devices = [
            {'path': '/dev/cu.SLAB_USBtoUART', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
            {'path': '/dev/cu.usbserial-0001', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'},
        ]
        original_len = len(devices)

        gui_common.dedupe_devices_by_node_id(devices, keep_path='/dev/cu.usbserial-0001')

        self.assertEqual(len(devices), original_len)


class TestDevicePathFromDisplay(unittest.TestCase):
    """Tests for device_path_from_display()."""

    def test_resolves_labeled_entry(self):
        """Given a formatted 'name (node_id)' display string, Then it
        resolves back to the underlying path."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]

        result = gui_common.device_path_from_display(devices, 'Meshtastic 4418 (!7c5b4418)')
        self.assertEqual(result, '/dev/ttyUSB0')

    def test_falls_back_for_unknown_text(self):
        """Given text that doesn't match any known device (a sentinel
        value, or a raw path not yet in devices), Then it's returned
        unchanged."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!7c5b4418', 'name': 'Meshtastic 4418'}]

        result = gui_common.device_path_from_display(devices, 'Auto-detect')
        self.assertEqual(result, 'Auto-detect')


class TestRefreshDeviceSpinnerLabels(unittest.TestCase):
    """Tests for refresh_device_spinner_labels()."""

    def test_preserves_selection_across_relabel(self):
        """Given the currently selected device gains a name/node_id, Then
        the spinner's values are rebuilt and its text updates to the new
        formatted label for that same device - not silently reset."""
        from gui import gui_common

        devices = [
            {'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': None},
            {'path': '/dev/ttyACM0', 'node_id': '!22222222', 'name': 'Node Two'},
        ]
        spinner = unittest.mock.MagicMock()
        spinner.text = '/dev/ttyACM0'  # selected before it had a label

        gui_common.refresh_device_spinner_labels(spinner, devices)

        self.assertEqual(
            spinner.values,
            ['/dev/ttyUSB0 (!11111111)', 'Node Two (!22222222)'],
        )
        self.assertEqual(spinner.text, 'Node Two (!22222222)')

    def test_unbinds_and_rebinds_selection_handler_when_given(self):
        """Given a selection_handler, Then it's unbound/rebound around the
        mutation, so relabeling never fires a spurious selection event."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': None}]
        spinner = unittest.mock.MagicMock()
        spinner.text = '/dev/ttyUSB0'
        handler = unittest.mock.MagicMock()

        gui_common.refresh_device_spinner_labels(spinner, devices, selection_handler=handler)

        spinner.unbind.assert_called_once_with(text=handler)
        spinner.bind.assert_called_once_with(text=handler)

    def test_no_bind_calls_when_selection_handler_omitted(self):
        """Given no selection_handler (the server GUI's case - no bound
        handler exists to protect), Then unbind/bind are never called."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': None}]
        spinner = unittest.mock.MagicMock()
        spinner.text = '/dev/ttyUSB0'

        gui_common.refresh_device_spinner_labels(spinner, devices)

        spinner.unbind.assert_not_called()
        spinner.bind.assert_not_called()

    def test_extra_values_stay_in_dropdown_across_relabel(self):
        """Given extra_values (e.g. the server GUI's "Auto-detect"
        sentinel, which isn't in `devices`), Then they're prepended to
        spinner.values on every rebuild - not silently dropped the moment
        an identity-probe result lands (2026-08-23 regression, found via
        real-hardware testing of Story 27.3)."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': None}]
        spinner = unittest.mock.MagicMock()
        spinner.text = '/dev/ttyUSB0'

        gui_common.refresh_device_spinner_labels(
            spinner, devices, extra_values=['Auto-detect']
        )

        self.assertEqual(spinner.values, ['Auto-detect', '/dev/ttyUSB0 (!11111111)'])

    def test_extra_values_defaults_to_empty_and_leaves_client_behavior_unchanged(self):
        """Given extra_values is omitted (the client GUI's case - no
        sentinel values), Then spinner.values contains only formatted
        devices, exactly as before this parameter was added."""
        from gui import gui_common

        devices = [{'path': '/dev/ttyUSB0', 'node_id': '!11111111', 'name': None}]
        spinner = unittest.mock.MagicMock()
        spinner.text = '/dev/ttyUSB0'

        gui_common.refresh_device_spinner_labels(spinner, devices)

        self.assertEqual(spinner.values, ['/dev/ttyUSB0 (!11111111)'])


if __name__ == '__main__':
    unittest.main()
