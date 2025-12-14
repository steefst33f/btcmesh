#!/usr/bin/env python3
"""
BTCMesh Server GUI - Kivy-based graphical interface for running and monitoring
the BTCMesh relay server.

This GUI wraps the btcmesh_server module, providing visual status displays,
activity logging, and server controls.
"""
import logging
import threading
import queue
import re
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.properties import BooleanProperty

# Import shared GUI components
from core.gui_common import (
    # Colors
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_BG,
    COLOR_SECUNDARY,
    COLOR_DISCONNECTED,
    # Classes
    ConnectionState,
    StatusLog,
    # Functions
    get_log_color,
    create_separator,
    create_section_label,
    create_title,
    create_action_button,
    create_clear_button,
)

# Import server module
import btcmesh_server
from core.logger_setup import server_logger


# Set window size for desktop
Window.size = (550, 700)

# Meshtastic connection states
STATE_MESHTASTIC_DISCONNECTED = ConnectionState('Meshtastic: Not connected', COLOR_DISCONNECTED)
STATE_MESHTASTIC_CONNECTED = ConnectionState('Meshtastic: Connected', COLOR_SUCCESS)
STATE_MESHTASTIC_FAILED = ConnectionState('Meshtastic: Connection failed', COLOR_ERROR)

# Bitcoin RPC connection states
STATE_RPC_DISCONNECTED = ConnectionState('Bitcoin RPC: Not connected', COLOR_DISCONNECTED)
STATE_RPC_CONNECTED = ConnectionState('Bitcoin RPC: Connected', COLOR_SUCCESS)
STATE_RPC_FAILED = ConnectionState('Bitcoin RPC: Connection failed', COLOR_ERROR)


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


def parse_log_for_status(message: str, level: int = None):  # noqa: ARG001
    """Parse a log message and return status update if applicable.

    Returns:
        Tuple of (status_type, data) or None if no status update needed.
    """
    # Bitcoin RPC status
    if "Connected to Bitcoin Core RPC node successfully" in message:
        # Extract host from "Host: localhost:8332" or "Host: *.onion"
        host_match = re.search(r'Host: ([^,]+)', message)
        host = host_match.group(1).strip() if host_match else None
        # Extract Tor status from "Tor: True" or "Tor: False"
        tor_match = re.search(r'Tor: (True|False)', message)
        is_tor = tor_match.group(1) == 'True' if tor_match else False
        return ('rpc_connected', {'host': host, 'is_tor': is_tor})
    if "Failed to connect to Bitcoin Core RPC node" in message:
        # Extract error message after the colon
        match = re.search(r'Failed to connect to Bitcoin Core RPC node: (.+?)(?:\. |$)', message)
        error = match.group(1) if match else "Connection failed"
        return ('rpc_failed', error)

    # Meshtastic status
    if "Meshtastic interface initialized successfully" in message:
        # Extract device path from "Device: /dev/ttyUSB0"
        device_match = re.search(r'Device: ([^,]+)', message)
        device = device_match.group(1).strip() if device_match else None
        # Extract node ID from "My Node Num: !abcdef12"
        node_match = re.search(r'My Node Num: (!?[0-9a-fA-F]+)', message)
        node_id = node_match.group(1) if node_match else "Unknown"
        return ('meshtastic_connected', {'node_id': node_id, 'device': device})
    if "Failed to initialize Meshtastic interface" in message:
        return ('meshtastic_failed', "Could not initialize Meshtastic")
    if "No Meshtastic device found" in message:
        return ('meshtastic_failed', "No device found")

    # Server running status
    if "Registered Meshtastic message handler. Waiting for messages" in message:
        return ('server_started', None)
    if "Stop signal received. Shutting down" in message:
        return ('server_stopping', None)
    if "Closing Meshtastic interface" in message:
        return ('server_stopped', None)

    # PubSub errors
    if "PubSub library not found" in message:
        return ('pubsub_error', "PubSub library not found")

    return None


class BTCMeshServerGUI(BoxLayout):
    """Main server GUI widget."""

    is_running = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 15
        self.spacing = 20

        # Server state
        self._stop_event = threading.Event()
        self._server_thread = None
        self._log_handler = None

        # Thread-safe result queue for communication
        self.result_queue = queue.Queue()

        # Set background color
        with self.canvas.before:
            Color(*COLOR_BG)
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

        self._build_ui()

        # Start polling for results from background threads
        Clock.schedule_interval(self._process_results, 0.1)

    def _update_rect(self, *args):
        """Update background rectangle on resize."""
        self.rect.pos = self.pos
        self.rect.size = self.size

    def _build_ui(self):
        """Build the GUI layout."""
        # Title
        self.add_widget(create_title('BTCMesh Relay Server'))

        # Orange separator line after title
        self.add_widget(create_separator())

        # Connection status section
        status_section = BoxLayout(orientation='vertical', size_hint_y=None, height=80, spacing=5)

        # Meshtastic status
        self.meshtastic_label = Label(
            text=STATE_MESHTASTIC_DISCONNECTED.text,
            size_hint_y=None,
            height=30,
            color=STATE_MESHTASTIC_DISCONNECTED.color,
            halign='left'
        )
        self.meshtastic_label.bind(size=self.meshtastic_label.setter('text_size'))
        status_section.add_widget(self.meshtastic_label)

        # Bitcoin RPC status
        self.rpc_label = Label(
            text=STATE_RPC_DISCONNECTED.text,
            size_hint_y=None,
            height=30,
            color=STATE_RPC_DISCONNECTED.color,
            halign='left'
        )
        self.rpc_label.bind(size=self.rpc_label.setter('text_size'))
        status_section.add_widget(self.rpc_label)

        self.add_widget(status_section)

        # Orange separator line after status section
        self.add_widget(create_separator())

        # Server controls
        controls_section = BoxLayout(orientation='horizontal', size_hint_y=None, height=50, spacing=10)

        self.start_btn = create_action_button('Start Server')
        self.start_btn.bind(on_press=self.on_start_pressed)
        controls_section.add_widget(self.start_btn)

        self.stop_btn = create_action_button('Stop Server', color=COLOR_ERROR, disabled=True)
        self.stop_btn.bind(on_press=self.on_stop_pressed)
        controls_section.add_widget(self.stop_btn)

        self.add_widget(controls_section)

        # Activity log section
        self.add_widget(create_section_label('Activity Log:'))

        # Status log (scrollable)
        self.status_log = StatusLog(size_hint_y=1)
        self.add_widget(self.status_log)

        # Clear log button
        self.clear_btn = create_clear_button(self.on_clear_pressed)
        self.add_widget(self.clear_btn)

        # Initial log message
        self.status_log.add_message("Server GUI initialized. Click 'Start Server' to begin.", COLOR_PRIMARY)

    def on_start_pressed(self, instance):
        """Handle Start Server button press."""
        self.status_log.add_message("Starting server...", COLOR_WARNING)
        self.start_btn.disabled = True

        # Reset stop event
        self._stop_event.clear()

        # Set up log handler to capture server logs
        self._log_handler = QueueLogHandler(self.result_queue)
        self._log_handler.setFormatter(logging.Formatter('%(message)s'))
        server_logger.addHandler(self._log_handler)

        # Start server in background thread
        def run_server():
            try:
                btcmesh_server.main(stop_event=self._stop_event)
            except Exception as e:
                self.result_queue.put(('init_error', str(e), logging.ERROR))
            finally:
                # Signal that server has stopped (in case main() exits without stop signal)
                if not self._stop_event.is_set():
                    self.result_queue.put(('server_stopped', None, logging.INFO))

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()

    def on_stop_pressed(self, instance):
        """Handle Stop Server button press."""
        self.status_log.add_message("Stopping server...", COLOR_WARNING)
        self.stop_btn.disabled = True

        # Signal server to stop
        self._stop_event.set()

    def _process_results(self, dt):
        """Process results from background threads (called by Clock)."""
        try:
            while True:
                result = self.result_queue.get_nowait()
                self._handle_result(result)
        except queue.Empty:
            pass

    def _handle_result(self, result):
        """Handle a single result from the queue."""
        result_type = result[0]
        data = result[1] if len(result) > 1 else None
        level = result[2] if len(result) > 2 else logging.INFO

        if result_type == 'log':
            # Parse log message for status updates
            status_update = parse_log_for_status(data, level)
            if status_update:
                self._apply_status_update(status_update)

            # Display log message with appropriate color
            color = get_log_color(level, data)
            self.status_log.add_message(data, color)

        elif result_type in ('rpc_connected', 'rpc_failed', 'meshtastic_connected',
                            'meshtastic_failed', 'server_started', 'server_stopped',
                            'server_stopping', 'pubsub_error', 'init_error'):
            self._apply_status_update((result_type, data))

    def _apply_status_update(self, status_update):
        """Apply a status update to the GUI."""
        status_type, data = status_update

        if status_type == 'rpc_connected':
            # data is dict with 'host' and 'is_tor' keys
            host = data.get('host') if isinstance(data, dict) else None
            is_tor = data.get('is_tor', False) if isinstance(data, dict) else False
            if host:
                tor_badge = " [Tor]" if is_tor else ""
                self.rpc_label.text = f"Bitcoin RPC: Connected ({host}){tor_badge}"
            else:
                self.rpc_label.text = STATE_RPC_CONNECTED.text
            self.rpc_label.color = STATE_RPC_CONNECTED.color

        elif status_type == 'rpc_failed':
            self.rpc_label.text = STATE_RPC_FAILED.text
            self.rpc_label.color = STATE_RPC_FAILED.color

        elif status_type == 'meshtastic_connected':
            # data is dict with 'node_id' and 'device' keys
            node_id = data.get('node_id', 'Unknown') if isinstance(data, dict) else data
            device = data.get('device') if isinstance(data, dict) else None
            if device:
                self.meshtastic_label.text = f"Meshtastic: Connected ({node_id}) on {device}"
            else:
                self.meshtastic_label.text = f"Meshtastic: Connected ({node_id})"
            self.meshtastic_label.color = STATE_MESHTASTIC_CONNECTED.color

        elif status_type == 'meshtastic_failed':
            self.meshtastic_label.text = STATE_MESHTASTIC_FAILED.text
            self.meshtastic_label.color = STATE_MESHTASTIC_FAILED.color
            # Re-enable start button on failure
            self.start_btn.disabled = False
            self._cleanup_log_handler()

        elif status_type == 'pubsub_error':
            self.start_btn.disabled = False
            self._cleanup_log_handler()

        elif status_type == 'server_started':
            self.is_running = True
            self.stop_btn.disabled = False

        elif status_type == 'server_stopping':
            # Server is in the process of stopping
            pass

        elif status_type == 'server_stopped':
            self.is_running = False
            self.meshtastic_label.text = STATE_MESHTASTIC_DISCONNECTED.text
            self.meshtastic_label.color = STATE_MESHTASTIC_DISCONNECTED.color
            self.rpc_label.text = STATE_RPC_DISCONNECTED.text
            self.rpc_label.color = STATE_RPC_DISCONNECTED.color
            # Note: stop_btn is set first because in tests, mocked buttons may be same object
            self.stop_btn.disabled = True
            self.start_btn.disabled = False
            self._cleanup_log_handler()

        elif status_type == 'init_error':
            self.status_log.add_message(f"Initialization error: {data}", COLOR_ERROR)
            self.start_btn.disabled = False
            self._cleanup_log_handler()

    def _cleanup_log_handler(self):
        """Remove log handler from server logger."""
        if self._log_handler:
            server_logger.removeHandler(self._log_handler)
            self._log_handler = None

    def on_clear_pressed(self, instance):
        """Handle Clear Log button press."""
        self.status_log.clear()
        self.status_log.add_message("Log cleared", COLOR_PRIMARY)


class BTCMeshServerApp(App):
    """Main Kivy application for the server GUI."""

    def build(self):
        self.title = 'BTCMesh Relay Server'
        Window.clearcolor = COLOR_BG
        return BTCMeshServerGUI()


def main():
    """Entry point for the server GUI."""
    BTCMeshServerApp().run()


if __name__ == '__main__':
    main()
