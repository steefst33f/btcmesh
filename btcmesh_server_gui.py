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
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
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
    COLOR_BG_LIGHT,
    COLOR_DISCONNECTED,
    COLOR_MAINNET,
    COLOR_TESTNET,
    COLOR_SIGNET,
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
    create_status_row,
    create_input_row,
    create_toggle_button,
)

# Import server module
import btcmesh_server
from core.logger_setup import server_logger
from core.config_loader import load_app_config


# Set window size for desktop
Window.size = (550, 850)

# Meshtastic connection states (text only - description is in separate label)
STATE_MESHTASTIC_DISCONNECTED = ConnectionState('Not connected', COLOR_DISCONNECTED)
STATE_MESHTASTIC_CONNECTED = ConnectionState('Connected', COLOR_SUCCESS)
STATE_MESHTASTIC_FAILED = ConnectionState('Connection failed', COLOR_ERROR)

# Bitcoin RPC connection states (text only - description is in separate label)
STATE_RPC_DISCONNECTED = ConnectionState('Not connected', COLOR_DISCONNECTED)
STATE_RPC_CONNECTED = ConnectionState('Connected', COLOR_SUCCESS)
STATE_RPC_FAILED = ConnectionState('Connection failed', COLOR_ERROR)


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
        # Extract chain from "Chain: main" or "Chain: testnet4" etc.
        chain_match = re.search(r'Chain: (\w+)', message)
        chain = chain_match.group(1) if chain_match else None
        return ('rpc_connected', {'host': host, 'is_tor': is_tor, 'chain': chain})
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
        # Validate device - reject invalid values like "None", "?", empty strings
        if device in (None, '', '?', 'None'):
            device = None
        # Extract node ID from "My Node Num: !abcdef12"
        node_match = re.search(r'My Node Num: (!?[0-9a-fA-F]+)', message)
        node_id = node_match.group(1) if node_match else None
        # If we don't have a valid node_id, treat as failed connection
        if not node_id or not node_id.startswith('!'):
            return ('meshtastic_failed', "Invalid device info")
        return ('meshtastic_connected', {'node_id': node_id, 'device': device})
    if "Failed to initialize Meshtastic interface" in message:
        return ('meshtastic_failed', "Could not initialize Meshtastic")
    if "Meshtastic interface created but could not retrieve device info" in message:
        return ('meshtastic_failed', "No device connected")
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
        status_section = BoxLayout(orientation='vertical', size_hint_y=None, height=110, spacing=5)

        # Network badge row (mainnet/testnet/signet)
        network_row, self.network_label = create_status_row(
            'Network:',
            '',
            initial_color=COLOR_DISCONNECTED,
            bold_value=True
        )
        status_section.add_widget(network_row)

        # Bitcoin RPC status row
        rpc_row, self.rpc_label = create_status_row(
            'Bitcoin RPC:',
            'Not connected',
            initial_color=COLOR_DISCONNECTED
        )
        status_section.add_widget(rpc_row)

        # Meshtastic status row
        meshtastic_row, self.meshtastic_label = create_status_row(
            'Meshtastic:',
            'Not connected',
            initial_color=COLOR_DISCONNECTED
        )
        status_section.add_widget(meshtastic_row)

        self.add_widget(status_section)

        # Orange separator line after status section
        self.add_widget(create_separator())

        # Bitcoin RPC Settings section
        self.add_widget(create_section_label('Bitcoin RPC Settings:'))
        self.add_widget(Widget(size_hint_y=None, height=2))
        self._build_rpc_settings()

        # Orange separator line after settings section
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

    def _build_rpc_settings(self):
        """Build the Bitcoin RPC settings input section."""
        import os

        # Load defaults from environment
        load_app_config()
        default_host = os.getenv("BITCOIN_RPC_HOST", "127.0.0.1")
        default_port = os.getenv("BITCOIN_RPC_PORT", "8332")
        default_user = os.getenv("BITCOIN_RPC_USER", "")
        default_password = os.getenv("BITCOIN_RPC_PASSWORD", "")

        settings_container = BoxLayout(orientation='vertical', size_hint_y=None, height=215, spacing=5)

        # Row 1: Host input with Show/Hide toggle
        host_row, self.rpc_host_input = create_input_row(
            'Host:', default_host, hint_text='127.0.0.1 or xyz.onion', password=True
        )
        # Show/Hide host toggle button
        self.show_host_btn = create_toggle_button('Show')
        self.show_host_btn.bind(on_press=self._toggle_host_visibility)
        host_row.add_widget(self.show_host_btn)
        settings_container.add_widget(host_row)

        # Row 2: Port input
        port_row, self.rpc_port_input = create_input_row(
            'Port:', default_port, hint_text='8332', input_filter='int'
        )
        # Spacer to align with host row (Show button = 60px)
        port_row.add_widget(Widget(size_hint_x=None, width=60))
        settings_container.add_widget(port_row)

        # Row 3: User input
        user_row, self.rpc_user_input = create_input_row(
            'User:', default_user, hint_text='rpcuser'
        )
        # Spacer to align with host row
        user_row.add_widget(Widget(size_hint_x=None, width=60))
        settings_container.add_widget(user_row)

        # Row 4: Password input with Show/Hide toggle
        pass_row, self.rpc_password_input = create_input_row(
            'Password:', default_password, hint_text='password', password=True
        )
        # Show/Hide password toggle button
        self.show_password_btn = create_toggle_button('Show')
        self.show_password_btn.bind(on_press=self._toggle_password_visibility)
        pass_row.add_widget(self.show_password_btn)
        settings_container.add_widget(pass_row)

        # add spacer
        settings_container.add_widget(Widget(size_hint_y=None, height=5))

        # Row 5: Test Connection button
        test_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=40, spacing=5)
        # Left spacer to center button
        test_row.add_widget(Widget(size_hint_x=0.3))

        self.test_connection_btn = Button(
            text='Test Connection',
            size_hint_x=0.4,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
        )
        self.test_connection_btn.bind(on_press=self._on_test_connection)
        test_row.add_widget(self.test_connection_btn)

        # Right spacer
        test_row.add_widget(Widget(size_hint_x=0.3))

        settings_container.add_widget(test_row)

        self.add_widget(settings_container)

    def _set_rpc_settings_enabled(self, enabled: bool):
        """Enable or disable all RPC settings inputs."""
        self.rpc_host_input.disabled = not enabled
        self.rpc_port_input.disabled = not enabled
        self.rpc_user_input.disabled = not enabled
        self.rpc_password_input.disabled = not enabled
        self.test_connection_btn.disabled = not enabled

    def _toggle_host_visibility(self, instance):
        """Toggle host field visibility."""
        self.rpc_host_input.password = not self.rpc_host_input.password
        self.show_host_btn.text = 'Hide' if not self.rpc_host_input.password else 'Show'

    def _toggle_password_visibility(self, instance):
        """Toggle password field visibility."""
        self.rpc_password_input.password = not self.rpc_password_input.password
        self.show_password_btn.text = 'Hide' if not self.rpc_password_input.password else 'Show'

    def _on_test_connection(self, instance):
        """Test the RPC connection with current settings."""
        host = self.rpc_host_input.text.strip()
        port = self.rpc_port_input.text.strip()
        user = self.rpc_user_input.text.strip()
        password = self.rpc_password_input.text

        # Basic validation
        if not host:
            self.status_log.add_message("Test failed: Host is required", COLOR_ERROR)
            return
        if not port:
            self.status_log.add_message("Test failed: Port is required", COLOR_ERROR)
            return
        if not user:
            self.status_log.add_message("Test failed: User is required", COLOR_ERROR)
            return
        if not password:
            self.status_log.add_message("Test failed: Password is required", COLOR_ERROR)
            return

        self.status_log.add_message("Testing RPC connection...", COLOR_WARNING)
        self.test_connection_btn.disabled = True
        self.start_btn.disabled = True

        def test_thread():
            try:
                # Check for Tor requirement
                is_tor = host.endswith('.onion')
                if is_tor:
                    # Validate Tor is available on port 9050
                    import socket
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(5)
                        result = sock.connect_ex(('127.0.0.1', 9050))
                        sock.close()
                        if result != 0:
                            self.result_queue.put(('test_connection_result', False,
                                                'Tor service not reachable on port 9050'))
                            return
                    except Exception as e:
                        self.result_queue.put(('test_connection_result', False,
                                            f'Failed to check Tor: {e}'))
                        return

                # Test RPC connection
                from core.rpc_client import BitcoinRPCClient
                config = {
                    'host': host,
                    'port': int(port),
                    'user': user,
                    'password': password,
                }
                client = BitcoinRPCClient(config)
                chain = client.chain
                tor_suffix = ' via Tor' if is_tor else ''
                self.result_queue.put(('test_connection_result', True,
                                    f'Connected to {chain} network{tor_suffix}'))
            except Exception as e:
                self.result_queue.put(('test_connection_result', False, str(e)))

        threading.Thread(target=test_thread, daemon=True).start()

    def on_start_pressed(self, instance):
        """Handle Start Server button press."""
        # Validate required fields before starting
        host = self.rpc_host_input.text.strip()
        port = self.rpc_port_input.text.strip()
        user = self.rpc_user_input.text.strip()
        password = self.rpc_password_input.text

        if not host or not port or not user or not password:
            self.status_log.add_message(
                "Cannot start: Please fill in all RPC settings fields", COLOR_ERROR)
            return

        self.status_log.add_message("Starting server...", COLOR_WARNING)
        self.start_btn.disabled = True
        self._set_rpc_settings_enabled(False)

        # Build RPC config from GUI inputs
        rpc_config = {
            'host': host,
            'port': int(port),
            'user': user,
            'password': password,
        }

        # Reset stop event
        self._stop_event.clear()

        # Set up log handler to capture server logs
        self._log_handler = QueueLogHandler(self.result_queue)
        self._log_handler.setFormatter(logging.Formatter('%(message)s'))
        server_logger.addHandler(self._log_handler)

        # Start server in background thread
        def run_server():
            try:
                btcmesh_server.main(stop_event=self._stop_event, rpc_config=rpc_config)
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

        elif result_type == 'test_connection_result':
            # data is success (bool), level is message string
            success = data
            message = level  # Third element contains the message
            self.test_connection_btn.disabled = False
            self.start_btn.disabled = False
            if success:
                self.status_log.add_message(f"RPC test successful: {message}", COLOR_SUCCESS)
            else:
                self.status_log.add_message(f"RPC test failed: {message}", COLOR_ERROR)

    def _apply_status_update(self, status_update):
        """Apply a status update to the GUI."""
        status_type, data = status_update

        if status_type == 'rpc_connected':
            # data is dict with 'host', 'is_tor', and 'chain' keys
            host = data.get('host') if isinstance(data, dict) else None
            is_tor = data.get('is_tor', False) if isinstance(data, dict) else False
            chain = data.get('chain') if isinstance(data, dict) else None
            if host:
                tor_badge = " [Tor]" if is_tor else ""
                self.rpc_label.text = f"Connected ({host}){tor_badge}"
            else:
                self.rpc_label.text = STATE_RPC_CONNECTED.text
            self.rpc_label.color = STATE_RPC_CONNECTED.color

            # Update network badge based on chain
            if chain:
                # Map chain values to display names and colors
                chain_display_map = {
                    'main': ('MAINNET', COLOR_MAINNET),
                    'test': ('TESTNET3', COLOR_TESTNET),
                    'testnet4': ('TESTNET4', COLOR_TESTNET),
                    'signet': ('SIGNET', COLOR_SIGNET),
                }
                display_name, color = chain_display_map.get(chain, (chain.upper(), COLOR_TESTNET))
                self.network_label.text = display_name
                self.network_label.color = color

        elif status_type == 'rpc_failed':
            self.rpc_label.text = STATE_RPC_FAILED.text
            self.rpc_label.color = STATE_RPC_FAILED.color

        elif status_type == 'meshtastic_connected':
            # data is dict with 'node_id' and 'device' keys
            node_id = data.get('node_id', 'Unknown') if isinstance(data, dict) else data
            device = data.get('device') if isinstance(data, dict) else None
            if device:
                self.meshtastic_label.text = f"Connected ({node_id}) on {device}"
            else:
                self.meshtastic_label.text = f"Connected ({node_id})"
            self.meshtastic_label.color = STATE_MESHTASTIC_CONNECTED.color

        elif status_type == 'meshtastic_failed':
            self.meshtastic_label.text = STATE_MESHTASTIC_FAILED.text
            self.meshtastic_label.color = STATE_MESHTASTIC_FAILED.color
            # Re-enable start button and settings on failure
            self.start_btn.disabled = False
            self._set_rpc_settings_enabled(True)
            self._cleanup_log_handler()

        elif status_type == 'pubsub_error':
            self.start_btn.disabled = False
            self._set_rpc_settings_enabled(True)
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
            self.network_label.text = ''
            self.network_label.color = COLOR_DISCONNECTED
            # Note: stop_btn is set first because in tests, mocked buttons may be same object
            self.stop_btn.disabled = True
            self.start_btn.disabled = False
            self._set_rpc_settings_enabled(True)
            self._cleanup_log_handler()

        elif status_type == 'init_error':
            self.status_log.add_message(f"Initialization error: {data}", COLOR_ERROR)
            self.start_btn.disabled = False
            self._set_rpc_settings_enabled(True)
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
