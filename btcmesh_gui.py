#!/usr/bin/env python3
"""
BTCMesh GUI Client - Kivy-based graphical interface for sending Bitcoin transactions
via Meshtastic LoRa relay.

This GUI wraps the btcmesh_cli module, displaying its log output in a graphical interface.
"""
import threading
import queue
import logging
import argparse
import io
import sys
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import StringProperty, BooleanProperty
from kivy.utils import get_color_from_hex

# Import btcmesh_cli functions
from btcmesh_cli import (
    is_valid_hex,
    initialize_meshtastic_interface_cli,
    cli_main,
    EXAMPLE_RAW_TX,
)

# Set window size for desktop testing
Window.size = (450, 700)

# Colors
COLOR_PRIMARY = get_color_from_hex('#FF6B00')  # Bitcoin orange
COLOR_SUCCESS = get_color_from_hex('#4CAF50')
COLOR_ERROR = get_color_from_hex('#F44336')
COLOR_WARNING = get_color_from_hex('#FF9800')
COLOR_BG = get_color_from_hex('#1E1E1E')
COLOR_BG_LIGHT = get_color_from_hex('#2D2D2D')
COLOR_SECUNDARY = get_color_from_hex("#FFFFFF")


def get_log_color(level, msg):
    """Determine the color for a log message based on level and content.

    Args:
        level: The logging level (e.g., logging.ERROR, logging.WARNING, logging.INFO)
        msg: The log message text

    Returns:
        A color tuple or None for default color
    """
    if level >= logging.ERROR:
        return COLOR_ERROR
    elif level >= logging.WARNING:
        return COLOR_WARNING
    elif 'success' in msg.lower() or 'ack' in msg.lower():
        return COLOR_SUCCESS
    return None


def get_print_color(msg):
    """Determine the color for a print message based on content.

    Args:
        msg: The message text

    Returns:
        A color tuple or None for default color
    """
    msg_lower = msg.lower()
    if 'error' in msg_lower or 'failed' in msg_lower or 'abort' in msg_lower:
        return COLOR_ERROR
    elif 'success' in msg_lower or 'txid' in msg_lower:
        return COLOR_SUCCESS
    return None


@dataclass
class ResultAction:
    """Represents the actions to take in response to a result from a background thread.

    This dataclass separates the logic of determining what to do from the actual
    GUI updates, making the logic testable without Kivy.
    """
    # Connection label updates
    connection_text: Optional[str] = None
    connection_color: Optional[Tuple] = None

    # Log messages to display: list of (message, color) tuples
    log_messages: List[Tuple[str, Optional[Tuple]]] = field(default_factory=list)

    # State changes
    stop_sending: bool = False

    # Popup actions
    show_success_popup: Optional[str] = None  # txid if success popup should be shown

    # Interface to store (for 'connected' result type)
    store_iface: Optional[Any] = None


def process_result(result: tuple) -> ResultAction:
    """Process a result tuple and return the actions to take.

    This is a pure function that determines what GUI actions should be performed
    based on the result, without actually performing them.

    Args:
        result: A tuple where result[0] is the result type string

    Returns:
        A ResultAction describing what GUI updates to make
    """
    action = ResultAction()
    result_type = result[0]

    if result_type == 'connected':
        iface = result[1]
        node_id = result[2]
        action.store_iface = iface
        action.connection_text = f'Meshtastic: Connected ({node_id})'
        action.connection_color = COLOR_SUCCESS
        action.log_messages.append((f"Connected to Meshtastic device: {node_id}", COLOR_SUCCESS))

    elif result_type == 'connection_failed':
        action.connection_text = 'Meshtastic: Connection failed'
        action.connection_color = COLOR_ERROR
        action.log_messages.append(("Failed to connect to Meshtastic device", COLOR_ERROR))

    elif result_type == 'connection_error':
        error = result[1]
        action.connection_text = 'Meshtastic: Error'
        action.connection_color = COLOR_ERROR
        action.log_messages.append((f"Connection error: {error}", COLOR_ERROR))

    elif result_type == 'log':
        msg = result[1]
        level = result[2]
        color = get_log_color(level, msg)
        action.log_messages.append((msg, color))

    elif result_type == 'print':
        msg = result[1]
        color = get_print_color(msg)
        action.log_messages.append((msg, color))

    elif result_type == 'cli_finished':
        exit_code = result[1]
        if exit_code == 0:
            action.log_messages.append(("Transaction completed successfully!", COLOR_SUCCESS))
        else:
            action.log_messages.append((f"CLI exited with code {exit_code}", COLOR_ERROR))
        action.stop_sending = True

    elif result_type == 'tx_success':
        txid = result[1]
        action.log_messages.append(("Transaction broadcast successful!", COLOR_SUCCESS))
        action.log_messages.append((f"TXID: {txid}", COLOR_SUCCESS))
        action.show_success_popup = txid
        action.stop_sending = True

    elif result_type == 'error':
        error = result[1]
        action.log_messages.append((f"Error: {error}", COLOR_ERROR))
        action.stop_sending = True

    elif result_type == 'aborted':
        action.log_messages.append(("Transaction aborted by user", COLOR_WARNING))
        action.stop_sending = True

    return action


def validate_send_inputs(dest: str, tx_hex: str, has_iface: bool) -> Optional[str]:
    """Validate the inputs for sending a transaction.

    This is a pure function that validates inputs without touching the GUI.

    Args:
        dest: The destination node ID
        tx_hex: The raw transaction hex (already cleaned of whitespace)
        has_iface: Whether the Meshtastic interface is connected

    Returns:
        An error message string if validation fails, or None if inputs are valid
    """
    if not dest:
        return "Enter destination node ID"

    if not dest.startswith('!'):
        return "Destination must start with '!'"

    if not tx_hex:
        return "Enter transaction hex"

    if len(tx_hex) % 2 != 0:
        return "Hex must have even length"

    if not is_valid_hex(tx_hex):
        return "Invalid hex characters"

    if not has_iface:
        return "Meshtastic not connected"

    return None


class QueueLogHandler(logging.Handler):
    """Custom log handler that sends log records to a queue for GUI display."""

    def __init__(self, result_queue):
        super().__init__()
        self.result_queue = result_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelno
            self.result_queue.put(('log', msg, level))
        except Exception:
            self.handleError(record)


class StatusLog(ScrollView):
    """Scrollable status/log area."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', size_hint_y=None, padding=5, spacing=2)
        self.layout.bind(minimum_height=self.layout.setter('height'))
        self.add_widget(self.layout)

    def add_message(self, text, color=None):
        """Add a log message with optional color."""
        label = Label(
            text=text,
            size_hint_y=None,
            height=25,
            text_size=(self.width - 20, None),
            halign='left',
            valign='middle',
            color=color or (1, 1, 1, 1),
        )
        label.bind(texture_size=lambda instance, value: setattr(instance, 'height', max(25, value[1] + 10)))
        self.layout.add_widget(label)
        # Auto-scroll to bottom
        self.scroll_y = 0

    def clear(self):
        """Clear all log messages."""
        self.layout.clear_widgets()


class BTCMeshGUI(BoxLayout):
    """Main GUI widget."""

    status_text = StringProperty('Ready')
    is_sending = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 15
        self.spacing = 20

        self.iface = None
        self.send_thread = None
        self.result_queue = queue.Queue()
        self.abort_requested = False

        self._build_ui()

        # Schedule periodic check for thread results
        Clock.schedule_interval(self._check_results, 0.1)

    def _build_ui(self):
        """Build the user interface."""
        # Title
        title_box = BoxLayout(size_hint_y=None, height=50, padding=15)
        title = Label(
            text='BTCMesh Transaction Relay',
            font_size=42,
            bold=True,
            color=COLOR_PRIMARY,
        )
        title_box.add_widget(title)
        self.add_widget(title_box)

        # Orange separator line
        separator1 = Widget(size_hint_y=None, height=2)
        with separator1.canvas:
            Color(*COLOR_PRIMARY)
            self._sep_rect1 = Rectangle(pos=separator1.pos, size=separator1.size)
        separator1.bind(pos=lambda inst, val: setattr(self._sep_rect1, 'pos', val))
        separator1.bind(size=lambda inst, val: setattr(self._sep_rect1, 'size', val))
        self.add_widget(separator1)

        # Destination input
        dest_label = Label(
            text='Destination Node ID:',
            size_hint_y=None,
            height=25,
            halign='left',
        )
        dest_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.add_widget(dest_label)
        self.dest_input = TextInput(
            hint_text='!abcdef12',
            multiline=False,
            size_hint_y=None,
            height=45,
            background_color=COLOR_BG_LIGHT,
            foreground_color=COLOR_SECUNDARY,
            cursor_color=COLOR_SECUNDARY,
        )
        self.add_widget(self.dest_input)

        # TX Hex input
        tx_label = Label(
            text='Raw Transaction Hex:',
            size_hint_y=None,
            height=25,
            halign='left',
        )
        tx_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.add_widget(tx_label)
        self.tx_input = TextInput(
            hint_text='Paste raw transaction hex here...',
            multiline=True,
            size_hint_y=None,
            height=180,
            background_color=COLOR_BG_LIGHT,
            foreground_color=COLOR_SECUNDARY,
            cursor_color=COLOR_SECUNDARY,
        )
        self.add_widget(self.tx_input)

        # Dry run toggle
        dry_run_box = BoxLayout(size_hint_y=None, height=40, spacing=10)

        # Label first, takes remaining space
        dry_run_label = Label(
            text='Dry run (simulate only)',
            size_hint_x=1,
            halign='left',
            valign='middle',
        )
        dry_run_label.bind(size=lambda inst, val: setattr(inst, 'text_size', val))
        dry_run_box.add_widget(dry_run_label)

        # Toggle button on the right with fixed width
        self.dry_run_toggle = ToggleButton(
            text='NO',
            size_hint_x=None,
            width=60,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
            background_down='',
        )

        def update_dry_run_toggle(instance, state):
            if state == 'down':
                instance.text = 'YES'
                instance.background_color = COLOR_PRIMARY
            else:
                instance.text = 'NO'
                instance.background_color = COLOR_BG_LIGHT

        self.dry_run_toggle.bind(state=update_dry_run_toggle)
        dry_run_box.add_widget(self.dry_run_toggle)

        self.add_widget(dry_run_box)

        # Orange separator line
        separator2 = Widget(size_hint_y=None, height=2)
        with separator2.canvas:
            Color(*COLOR_PRIMARY)
            self._sep_rect2 = Rectangle(pos=separator2.pos, size=separator2.size)
        separator2.bind(pos=lambda inst, val: setattr(self._sep_rect2, 'pos', val))
        separator2.bind(size=lambda inst, val: setattr(self._sep_rect2, 'size', val))
        self.add_widget(separator2)

        # Button row
        btn_box = BoxLayout(size_hint_y=None, height=50, spacing=10)

        self.send_btn = Button(
            text='Send Transaction',
            background_color=COLOR_PRIMARY,
            background_normal='',
            bold=True,
        )
        self.send_btn.bind(on_press=self.on_send_pressed)
        btn_box.add_widget(self.send_btn)

        self.example_btn = Button(
            text='Load Example',
            background_color=COLOR_BG_LIGHT,
            background_normal='',
        )
        self.example_btn.bind(on_press=self.on_load_example)
        btn_box.add_widget(self.example_btn)

        self.abort_btn = Button(
            text='Abort',
            background_color=COLOR_ERROR,
            background_normal='',
            disabled=True,
        )
        self.abort_btn.bind(on_press=self.on_abort_pressed)
        btn_box.add_widget(self.abort_btn)

        self.add_widget(btn_box)

        # Connection status
        self.connection_label = Label(
            text='Meshtastic: Not connected',
            size_hint_y=None,
            height=25,
            color=(0.7, 0.7, 0.7, 1),
        )
        self.add_widget(self.connection_label)

        # Status/Log area
        log_label = Label(
            text='Status Log:',
            size_hint_y=None,
            height=25,
            halign='left',
        )
        log_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.add_widget(log_label)
        self.status_log = StatusLog(size_hint_y=1)
        self.add_widget(self.status_log)

        # Clear button at bottom
        self.clear_btn = Button(
            text='Clear Log',
            size_hint_y=None,
            height=40,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
        )
        self.clear_btn.bind(on_press=self.on_clear)
        self.add_widget(self.clear_btn)

        # Try to connect to Meshtastic on startup
        Clock.schedule_once(lambda dt: self._init_meshtastic(), 1)

    def _init_meshtastic(self):
        """Initialize Meshtastic interface in background."""
        self.status_log.add_message("Connecting to Meshtastic device...")

        def init_thread():
            try:
                iface = initialize_meshtastic_interface_cli()
                if iface:
                    node_id = "Unknown"
                    if hasattr(iface, 'myInfo') and iface.myInfo:
                        node_id = f"!{iface.myInfo.my_node_num:x}"
                    self.result_queue.put(('connected', iface, node_id))
                else:
                    self.result_queue.put(('connection_failed', None, None))
            except Exception as e:
                self.result_queue.put(('connection_error', str(e), None))

        threading.Thread(target=init_thread, daemon=True).start()

    def _check_results(self, dt):
        """Check for results from background threads."""
        try:
            while True:
                result = self.result_queue.get_nowait()
                self._handle_result(result)
        except queue.Empty:
            pass

    def _handle_result(self, result):
        """Handle a result from a background thread.

        Uses process_result to determine actions, then applies them to the GUI.
        """
        action = process_result(result)

        # Apply connection label updates
        if action.connection_text is not None:
            self.connection_label.text = action.connection_text
        if action.connection_color is not None:
            self.connection_label.color = action.connection_color

        # Store interface if provided
        if action.store_iface is not None:
            self.iface = action.store_iface

        # Add log messages
        for msg, color in action.log_messages:
            self.status_log.add_message(msg, color)

        # Handle state changes
        if action.stop_sending:
            self.is_sending = False
            self.send_btn.disabled = False
            self.abort_btn.disabled = True

        # Show popups
        if action.show_success_popup is not None:
            self._show_success_popup(action.show_success_popup)

    def on_send_pressed(self, instance):
        """Handle send button press."""
        dest = self.dest_input.text.strip()
        tx_hex = self.tx_input.text.strip().replace('\n', '').replace(' ', '')

        # Validation
        error = validate_send_inputs(dest, tx_hex, bool(self.iface))
        if error:
            self.status_log.add_message(f"Error: {error}", COLOR_ERROR)
            if error == "Meshtastic not connected":
                self._init_meshtastic()
            return

        # Start sending
        self.is_sending = True
        self.send_btn.disabled = True
        self.abort_btn.disabled = False
        self.abort_requested = False
        self.status_log.clear()
        dry_run = self.dry_run_toggle.state == 'down'
        if dry_run:
            self.status_log.add_message(f"Starting DRY RUN transaction send to {dest}...")
        else:
            self.status_log.add_message(f"Starting transaction send to {dest}...")

        # Run send in background thread
        self.send_thread = threading.Thread(
            target=self._send_transaction_thread,
            args=(dest, tx_hex, dry_run),
            daemon=True
        )
        self.send_thread.start()

    def _send_transaction_thread(self, dest, tx_hex, dry_run):
        """Send transaction in background thread using cli_main."""
        gui_instance = self  # Reference to check abort_requested

        class AbortedException(Exception):
            """Raised when user requests abort."""
            pass

        try:
            # Create a custom logger that sends to our queue
            gui_logger = logging.getLogger('btcmesh_gui')
            gui_logger.setLevel(logging.DEBUG)
            gui_logger.handlers.clear()  # Remove any existing handlers

            queue_handler = QueueLogHandler(self.result_queue)
            queue_handler.setFormatter(logging.Formatter('%(message)s'))
            gui_logger.addHandler(queue_handler)

            # Create args namespace to pass to cli_main
            args = argparse.Namespace(
                destination=dest,
                tx=tx_hex,
                dry_run=dry_run,
                session_id=None  # Let cli_main generate one
            )

            # Capture print output by redirecting stdout
            class PrintCapture(io.StringIO):
                def __init__(self, result_queue):
                    super().__init__()
                    self.result_queue = result_queue
                    self.original_stdout = sys.stdout

                def write(self, text):
                    # Check for abort request
                    if gui_instance.abort_requested:
                        raise AbortedException()
                    # Write to original stdout for debugging
                    self.original_stdout.write(text)
                    # Send non-empty lines to the queue
                    text = text.strip()
                    if text:
                        self.result_queue.put(('print', text))
                    return len(text)

                def flush(self):
                    self.original_stdout.flush()

            # Check for abort before starting
            if self.abort_requested:
                self.result_queue.put(('aborted',))
                return

            # Run cli_main with our injected logger and interface
            print_capture = PrintCapture(self.result_queue)
            original_stdout = sys.stdout

            try:
                sys.stdout = print_capture
                exit_code = cli_main(
                    args=args,
                    injected_iface=self.iface,
                    injected_logger=gui_logger
                )
            finally:
                sys.stdout = original_stdout

            # Check for abort after completion
            if self.abort_requested:
                self.result_queue.put(('aborted',))
            else:
                self.result_queue.put(('cli_finished', exit_code))

        except AbortedException:
            self.result_queue.put(('aborted',))
        except Exception as e:
            gui_logger.error(f"GUI send error: {e}", exc_info=True)
            self.result_queue.put(('error', str(e)))

    def _show_success_popup(self, txid):
        """Show success popup with TXID."""
        content = BoxLayout(orientation='vertical', padding=20, spacing=10)
        content.add_widget(Label(text='Transaction Sent!', font_size=18, bold=True))
        content.add_widget(Label(text=f'TXID:\n{txid}', text_size=(300, None)))

        ok_btn = Button(text='OK', size_hint_y=None, height=40)
        content.add_widget(ok_btn)

        popup = Popup(
            title='Success',
            content=content,
            size_hint=(0.9, 0.4),
            auto_dismiss=True,
        )
        ok_btn.bind(on_press=popup.dismiss)
        popup.open()

    def on_load_example(self, instance):
        """Load example transaction and destination."""
        self.dest_input.text = '!abcd1234'
        self.tx_input.text = EXAMPLE_RAW_TX
        self.status_log.add_message("Loaded example destination and transaction")

    def on_abort_pressed(self, instance):
        """Handle abort button press."""
        if self.is_sending:
            self.abort_requested = True
            self.status_log.add_message("Abort requested...", COLOR_WARNING)
            self.abort_btn.disabled = True

    def on_clear(self, instance):
        """Clear the status log."""
        self.status_log.clear()
        self.status_log.add_message("Log cleared")


class BTCMeshApp(App):
    """Main Kivy application."""

    def build(self):
        self.title = 'BTCMesh Client'
        Window.clearcolor = COLOR_BG
        return BTCMeshGUI()

    def on_stop(self):
        """Cleanup on app close."""
        if hasattr(self.root, 'iface') and self.root.iface:
            try:
                self.root.iface.close()
            except:
                pass


def main():
    """Entry point for GUI."""
    BTCMeshApp().run()


if __name__ == '__main__':
    main()
