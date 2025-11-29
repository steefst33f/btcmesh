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
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
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
    show_failed_popup: bool = False

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
        action.show_failed_popup = True
        action.stop_sending = True

    return action


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
        self.spacing = 10

        self.iface = None
        self.send_thread = None
        self.result_queue = queue.Queue()

        self._build_ui()

        # Schedule periodic check for thread results
        Clock.schedule_interval(self._check_results, 0.1)

    def _build_ui(self):
        """Build the user interface."""
        # Title
        title_box = BoxLayout(size_hint_y=None, height=50)
        title = Label(
            text='BTCMesh Transaction Relay',
            font_size=22,
            bold=True,
            color=COLOR_PRIMARY,
        )
        title_box.add_widget(title)
        self.add_widget(title_box)

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
            foreground_color=(1, 1, 1, 1),
            cursor_color=(1, 1, 1, 1),
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
            foreground_color=(1, 1, 1, 1),
            cursor_color=(1, 1, 1, 1),
        )
        self.add_widget(self.tx_input)

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

        self.clear_btn = Button(
            text='Clear',
            background_color=COLOR_BG_LIGHT,
            background_normal='',
        )
        self.clear_btn.bind(on_press=self.on_clear)
        btn_box.add_widget(self.clear_btn)

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

        # Show popups
        if action.show_success_popup is not None:
            self._show_success_popup(action.show_success_popup)
        if action.show_failed_popup:
            self._show_failed_popup()

    def on_send_pressed(self, instance):
        """Handle send button press."""
        dest = self.dest_input.text.strip()
        tx_hex = self.tx_input.text.strip().replace('\n', '').replace(' ', '')

        # Validation
        if not dest:
            self.status_log.add_message("Error: Enter destination node ID", COLOR_ERROR)
            return

        if not dest.startswith('!'):
            self.status_log.add_message("Error: Destination must start with '!'", COLOR_ERROR)
            return

        if not tx_hex:
            self.status_log.add_message("Error: Enter transaction hex", COLOR_ERROR)
            return

        if len(tx_hex) % 2 != 0:
            self.status_log.add_message("Error: Hex must have even length", COLOR_ERROR)
            return

        if not is_valid_hex(tx_hex):
            self.status_log.add_message("Error: Invalid hex characters", COLOR_ERROR)
            return

        if not self.iface:
            self.status_log.add_message("Error: Meshtastic not connected", COLOR_ERROR)
            self._init_meshtastic()
            return

        # Start sending
        self.is_sending = True
        self.send_btn.disabled = True
        self.status_log.clear()
        self.status_log.add_message(f"Starting transaction send to {dest}...")

        # Run send in background thread
        self.send_thread = threading.Thread(
            target=self._send_transaction_thread,
            args=(dest, tx_hex),
            daemon=True
        )
        self.send_thread.start()

    def _send_transaction_thread(self, dest, tx_hex):
        """Send transaction in background thread using cli_main."""
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
                dry_run=False,
                session_id=None  # Let cli_main generate one
            )

            # Capture print output by redirecting stdout
            class PrintCapture(io.StringIO):
                def __init__(self, result_queue):
                    super().__init__()
                    self.result_queue = result_queue
                    self.original_stdout = sys.stdout

                def write(self, text):
                    # Write to original stdout for debugging
                    self.original_stdout.write(text)
                    # Send non-empty lines to the queue
                    text = text.strip()
                    if text:
                        self.result_queue.put(('print', text))
                    return len(text)

                def flush(self):
                    self.original_stdout.flush()

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

            self.result_queue.put(('cli_finished', exit_code))

        except Exception as e:
            gui_logger.error(f"GUI send error: {e}", exc_info=True)
            self.result_queue.put(('error', str(e)))

    def _show_success_popup(self, txid):
        """Show success popup with TXID."""
        content = BoxLayout(orientation='vertical', padding=20, spacing=10)
        content.add_widget(Label(text='Transaction Sent!', font_size=18, bold=True))
        content.add_widget(Label(text=f'TXID:\n{txid}', text_size=(300, None)))

        close_btn = Button(text='Close', size_hint_y=None, height=40)
        content.add_widget(close_btn)

        popup = Popup(
            title='Success',
            content=content,
            size_hint=(0.9, 0.4),
            auto_dismiss=True,
        )
        close_btn.bind(on_press=popup.dismiss)
        popup.open()

    def _show_failed_popup(self):
        """Show failed popup."""
        content = BoxLayout(orientation='vertical', padding=20, spacing=10)
        content.add_widget(Label(text='Transaction Broadcast Failed!', font_size=18, bold=True))

        close_btn = Button(text='Close', size_hint_y=None, height=40)
        content.add_widget(close_btn)

        popup = Popup(
            title='Failed',
            content=content,
            size_hint=(0.9, 0.4),
            auto_dismiss=True,
        )
        close_btn.bind(on_press=popup.dismiss)
        popup.open()


    def on_load_example(self, instance):
        """Load example transaction."""
        self.tx_input.text = EXAMPLE_RAW_TX
        self.status_log.add_message("Loaded example transaction")

    def on_clear(self, instance):
        """Clear all inputs and logs."""
        self.dest_input.text = ''
        self.tx_input.text = ''
        self.status_log.clear()
        self.status_log.add_message("Cleared")


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
