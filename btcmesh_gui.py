#!/usr/bin/env python3
"""
BTCMesh GUI Client - Kivy-based graphical interface for sending Bitcoin transactions
via Meshtastic LoRa relay.

All business logic lives in client/sender.py (chunking, ARQ, retries) and
transport/meshtastic_serial.py (device connection). This file only handles
UI concerns: widget setup, user interaction, and displaying progress/results.
"""
import threading
import queue
import logging
import argparse
import io
import sys
import time
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
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, BooleanProperty

# Import shared GUI components
from core.gui_common import (
    # Colors
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_BG,
    COLOR_BG_LIGHT,
    COLOR_SECUNDARY,
    COLOR_DISCONNECTED,
    # Classes
    ConnectionState,
    StatusLog,
    # Functions
    get_log_color,
    get_print_color,
    create_separator,
    create_section_label,
    create_title,
    create_action_button,
    create_clear_button,
    create_refresh_button,
    create_popup_button,
)

# Import Meshtastic utilities from core
from core.meshtastic_utils import (
    scan_meshtastic_devices,
    get_own_node_id,
    get_own_node_name,
    get_known_nodes,
    format_node_display,
)

# Import transport layer
from transport.meshtastic_serial import MeshtasticSerialTransport

# Import transaction sending logic
from client.sender import TransactionSender, SendResult, create_preview
from core.protocol import is_valid_hex

# Device selection constants
NO_DEVICES_TEXT = "No devices found"
SCANNING_TEXT = "Scanning..."
SELECT_DEVICE_TEXT = "Select a device to connect..."

# Connection retry settings: a freshly enumerated serial port (or one just
# released by a prior disconnect) can transiently fail to open for a moment;
# retry a few times before giving up instead of hanging indefinitely.
CONNECT_MAX_ATTEMPTS = 4
CONNECT_RETRY_DELAY_SECONDS = 1.5

# Example raw transaction for testing (see reference_materials.md)
EXAMPLE_RAW_TX = (
    "02000000000108bf2c7da5efaf2708170ffbafde7b2b0ca68234474ea71d443aee6aebf"
    "bf998030000000000fdffffffd6fcdbf37f974be27e8b0d66638355e5f53bfaf7b930fa"
    "e035d23b313c4751042900000000fdffffffcccc5ca913b8eb426fd7c6bb578eab0f265"
    "83d40c51ce52cb12a428c1e75f7320100000000fdffffff981b8b54ad2a8bd8b59d063e"
    "9473aead87412b699cb969298cf29b8787fe10600000000000fdffffff5d154c445b35a"
    "92aaf179c078cdab6310e69455cde650f128cbe85d92bab51600100000000fdffffff7"
    "d23c74a412ef33d5dd856d01933dd6a5453aee3539b12349febbf6c1ba1579801000000"
    "00fdffffffc5c95ce2eac84fbd3db87bbbdb4cc0855088e891cc57b1f9e0684943a399a"
    "abf0000000000fdffffffb7ef5d8a55141068da0d7b5a712ad9bbe44c3b8b412d0df5b9"
    "bcad366d71c8f90500000000fdffffff01697c63030000000016001482ea8436a6318c9"
    "89767a51ce33886d65faf59a10247304402203ec9cfb2b60a7b1df545493d1794fec0b8"
    "b6d8589f562f61c9aec6852775b54102205dfb34dcc9cc31110fdf4e4544c76e9a664cf"
    "29e8f1f9905771db386882527190121030e92cc6f0829ea8b91469c8aa7ca0660d66020"
    "d3e8baaece478905e0c30c1f770247304402204a3a6a7a5d4ff285b1ba4a3457dae8566"
    "a1616738f94e9eddcce6a75dbb831ef0220285c586f6463dcf68ccef59484b2d12bccd7"
    "d68a68b7092068e6cbfd96f04d88012102f48b8ab9a082a1cf94dcd7052ddea7d260b40"
    "cf01e83aa3df00f2266721ef420024730440220527c3eb66a06d697a078b2b2bdf9be52"
    "f9fe036b1e3422a0a150e151ff0cd25b0220268688d8d9a3dd24b9f846b1b2f1b1f1ed8"
    "4443f0023e26fa1ac5f2c1f0626ac012103acc2fbe36c425eb49389e5896232ef90beda"
    "75531845cd726dfed5f60a1fedd10247304402202eee600a307d10fc4777e8143d3db89"
    "94a6e742d56d4e3ce67a21a1e5e509178022022ee1b1fee5d7ec8112a56b1c0ab2eef1b"
    "e00907d384bbf10a7a9d2d27564fb5012103bd6876311fbf657af0c1c85e907c3adf8d5"
    "086d1b3cf2cd4805b40873d2cf3cd02473044022042dbc6204b70da1548456beef504d5"
    "e8d61349dd36913832060b35f61a360429022006940b48cff72f6476b8d449512661876"
    "6500f0868fb99ba40ab518934e9cc2b0121035aa46c0cf9b30a9edf20c65e5c39158aef"
    "bfdd2b7a049d146f42b7dc3163d1b50247304402207811bd5b127e8a693f20115f7f8b8"
    "b4dec6a4d5df32109b21e1252331778ac5202202ac727cc6c53287110fcd371845b5fcd"
    "ba825cb9e60992cc01cffa8e2ee41701012102700455a96ddb63fdaf8fc3ad60d02b057"
    "f8e00ed512476d817150a22fd4495d90247304402202caf8f9c584fe1b5214dc2a67f42"
    "fe3b9fd7386b98807fc6bc273a2cf519769902201f9f7b407f92c7df84701e4259acb19"
    "8ca19c5edbd860385caa6ca1316417c010121035bfcbb577fe3a3a805c78226c7e7c573"
    "053e85e6641243c8f435acde0e04668902473044022074d6273ed2c7f338c9db6a979f6"
    "4f572a21e5a324eec4979dad77383b25263de02202635d0e21ddf4e46f5751d4d6117ad"
    "559f04b7a6d3d00f13dd784b82a902638e012103de05dcec6736d4e15dd88c5b34b638f"
    "ee6cccfd8b260d53379a43be0b343617cd9540c00"
)

# Node selection constants
NO_NODES_TEXT = "No nodes found"
MANUAL_ENTRY_TEXT = "Enter manually..."

# Set window size for desktop testing
Window.size = (450, 700)

# Connection states (using ConnectionState from gui_common)
STATE_DISCONNECTED = ConnectionState('Meshtastic: Not connected', COLOR_DISCONNECTED)
STATE_CONNECTION_FAILED = ConnectionState('Meshtastic: Connection failed', COLOR_ERROR)
STATE_CONNECTION_ERROR = ConnectionState('Meshtastic: Error', COLOR_ERROR)


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
        node_name = result[3] if len(result) > 3 else None
        action.store_iface = iface
        if node_name:
            action.connection_text = f'Meshtastic: Connected - {node_name} ({node_id})'
            action.log_messages.append((f"Connected to Meshtastic device: {node_name} ({node_id})", COLOR_SUCCESS))
        else:
            action.connection_text = f'Meshtastic: Connected ({node_id})'
            action.log_messages.append((f"Connected to Meshtastic device: {node_id}", COLOR_SUCCESS))
        action.connection_color = COLOR_SUCCESS

    elif result_type == 'connection_failed':
        action.connection_text = STATE_CONNECTION_FAILED.text
        action.connection_color = STATE_CONNECTION_FAILED.color
        # Use specific error message if provided, otherwise generic message
        error_msg = result[1] if len(result) > 1 and result[1] else "Failed to connect to Meshtastic device"
        action.log_messages.append((error_msg, COLOR_ERROR))

    elif result_type == 'connection_error':
        error = result[1]
        action.connection_text = STATE_CONNECTION_ERROR.text
        action.connection_color = STATE_CONNECTION_ERROR.color
        action.log_messages.append((f"Connection error: {error}", COLOR_ERROR))

    elif result_type == 'connection_initializing':
        # Device is still initializing - show informational message
        action.log_messages.append(("Device is initializing, please wait...", COLOR_WARNING))
        action.connection_text = 'Meshtastic: Initializing...'
        action.connection_color = COLOR_WARNING

    elif result_type == 'log':
        msg = result[1]
        level = result[2]
        color = get_log_color(level, msg)
        action.log_messages.append((msg, color))

    elif result_type == 'print':
        # Old CLI result type - kept for backwards compatibility, will be removed in Step 7
        msg = result[1]
        color = get_print_color(msg)
        action.log_messages.append((msg, color))

        # Detect success message with TXID and trigger popup
        if 'TXID:' in msg and 'successfully' in msg.lower():
            txid_start = msg.find('TXID:') + 5
            txid = msg[txid_start:].strip().split()[0] if txid_start > 5 else 'Unknown'
            action.show_success_popup = txid
            action.stop_sending = True

    elif result_type == 'chunk_sending':
        chunk_num, total, attempt = result[1], result[2], result[3]
        if attempt > 1:
            msg = f'Sending chunk {chunk_num}/{total} (retry {attempt - 1})...'
        else:
            msg = f'Sending chunk {chunk_num}/{total}...'
        action.log_messages.append((msg, COLOR_PRIMARY))

    elif result_type == 'wire_sent':
        wire_format = result[1]
        action.log_messages.append((f'  -> {wire_format}', COLOR_SECUNDARY))

    elif result_type == 'progress':
        chunk_num, total = result[1], result[2]
        if chunk_num == total:
            msg = f'Chunk {chunk_num}/{total} sent — waiting for broadcast...'
        else:
            msg = f'Chunk {chunk_num}/{total} sent'
        action.log_messages.append((msg, COLOR_PRIMARY))

    elif result_type == 'wire_received':
        message_text = result[1]
        action.log_messages.append((f'  <- {message_text}', COLOR_SECUNDARY))

    elif result_type == 'send_result':
        send_result = result[1]
        if send_result.success:
            action.show_success_popup = send_result.txid
            action.stop_sending = True
        elif send_result.error == "Aborted by user":
            action.log_messages.append(('Transaction aborted by user', COLOR_WARNING))
            action.stop_sending = True
        else:
            action.log_messages.append((f'Error: {send_result.error}', COLOR_ERROR))
            action.stop_sending = True

    elif result_type == 'cli_finished':
        # Old CLI result type - kept for backwards compatibility, will be removed in Step 7
        exit_code = result[1]
        if exit_code == 0:
            action.log_messages.append(("Transaction completed successfully!", COLOR_SUCCESS))
        else:
            action.log_messages.append((f"CLI exited with code {exit_code}", COLOR_ERROR))
        action.stop_sending = True

    elif result_type == 'tx_success':
        # Old result type - kept for backwards compatibility, will be removed in Step 7
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


def validate_send_inputs(dest: str, tx_hex: str, has_iface: bool, dry_run: bool = False,
                        own_node_id: Optional[str] = None) -> Optional[str]:
    """Validate the inputs for sending a transaction.

    This is a pure function that validates inputs without touching the GUI.

    Args:
        dest: The destination node ID
        tx_hex: The raw transaction hex (already cleaned of whitespace)
        has_iface: Whether the Meshtastic interface is connected
        dry_run: Whether this is a dry run (skips Meshtastic connection check)
        own_node_id: The node ID of the connected device (for self-send check)

    Returns:
        An error message string if validation fails, or None if inputs are valid
    """
    if not dest:
        return "Enter destination node ID"

    if not dest.startswith('!'):
        return "Destination must start with '!'"

    # Check for sending to own node
    if own_node_id and dest.lower() == own_node_id.lower():
        return "Cannot send to your own node"

    if not tx_hex:
        return "Enter transaction hex"

    if len(tx_hex) % 2 != 0:
        return "Hex must have even length"

    if not is_valid_hex(tx_hex):
        return "Invalid hex characters"

    if not has_iface and not dry_run:
        return "Meshtastic not connected"

    return None


class BTCMeshGUI(BoxLayout):
    """Main GUI widget."""

    status_text = StringProperty('Ready')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 15
        self.spacing = 20

        self.transport = None
        self.iface = None
        self.send_thread = None
        self.result_queue = queue.Queue()
        self._connection_monitor = None  # Track the connection state monitor
        self._active_sender = None  # Track the active TransactionSender instance

        self._build_ui()

        # Schedule periodic check for thread results
        Clock.schedule_interval(self._check_results, 0.1)

    def _build_ui(self):
        """Build the user interface."""
        # Title
        self.add_widget(create_title('BTCMesh Transaction Relay'))

        # Orange separator line
        self.add_widget(create_separator())

        # Device selection row
        self.add_widget(create_section_label('Your Device:'))

        device_selection_box = BoxLayout(size_hint_y=None, height=40, spacing=10)

        # Spinner (drop down list)
        self.device_spinner = Spinner(
            text=SCANNING_TEXT,
            values=[],
            size_hint_x=1,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
            color=COLOR_SECUNDARY,
        )
        self.device_spinner.bind(text=self.on_device_selected)
        device_selection_box.add_widget(self.device_spinner)

        # Refresh button
        self.refresh_btn = create_refresh_button('Scan')
        self.refresh_btn.bind(on_press=self.on_refresh_devices)
        device_selection_box.add_widget(self.refresh_btn)

        self.add_widget(device_selection_box)

        # Destination input section
        self.add_widget(create_section_label('Destination Node ID:'))

        # Node selection row (Spinner + TextInput + Refresh)
        dest_selection_box = BoxLayout(size_hint_y=None, height=45, spacing=5)

        # Known nodes cache for mapping display text back to node id
        self.known_nodes = []

        # Spinner for known nodes
        self.node_spinner = Spinner(
            text=MANUAL_ENTRY_TEXT,
            values=[MANUAL_ENTRY_TEXT],
            size_hint_x=0.5,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
            color=COLOR_SECUNDARY,
        )
        self.node_spinner.bind(text=self.on_node_selected)
        dest_selection_box.add_widget(self.node_spinner)

        # TextInput for destination (manual entry or selected from dropdown)
        self.dest_input = TextInput(
            hint_text='!node_id',
            multiline=False,
            size_hint_x=0.4,
            background_color=COLOR_BG_LIGHT,
            foreground_color=COLOR_SECUNDARY,
            cursor_color=COLOR_SECUNDARY,
        )
        dest_selection_box.add_widget(self.dest_input)

        # Refresh nodes button
        self.refresh_nodes_btn = create_refresh_button('Scan')
        self.refresh_nodes_btn.bind(on_press=self.on_refresh_nodes)
        dest_selection_box.add_widget(self.refresh_nodes_btn)

        self.add_widget(dest_selection_box)

        # TX Hex input
        self.add_widget(create_section_label('Raw Transaction Hex:'))
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
        dry_run_box.add_widget(create_section_label('Dry run (simulate only)'))

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
        self.add_widget(create_separator())

        # Button row
        btn_box = BoxLayout(size_hint_y=None, height=50, spacing=10)

        self.send_btn = create_action_button('Send Transaction')
        self.send_btn.bind(on_press=self.on_send_pressed)
        btn_box.add_widget(self.send_btn)

        self.example_btn = create_action_button('Load Hex Example', color=COLOR_BG_LIGHT, bold=False)
        self.example_btn.bind(on_press=self.on_load_example)
        btn_box.add_widget(self.example_btn)

        self.abort_btn = create_action_button('Abort', color=COLOR_ERROR, disabled=True)
        self.abort_btn.bind(on_press=self.on_abort_pressed)
        btn_box.add_widget(self.abort_btn)

        self.add_widget(btn_box)

        # Connection status
        self.connection_label = Label(
            text=STATE_DISCONNECTED.text,
            size_hint_y=None,
            height=25,
            color=STATE_DISCONNECTED.color,
        )
        self.add_widget(self.connection_label)

        # Status/Log area
        self.add_widget(create_section_label('Activity Log:'))
        self.status_log = StatusLog(size_hint_y=1)
        self.add_widget(self.status_log)

        # Clear button at bottom
        self.clear_btn = create_clear_button(self.on_clear)
        self.add_widget(self.clear_btn)

        # Scan for devices on startup
        Clock.schedule_once(lambda dt: self._scan_devices(), 1)

    def _scan_devices(self):
        """Scan for available Meshtastic devices in background."""
        self.device_spinner.text = SCANNING_TEXT
        self.status_log.add_message("Scanning for Meshtastic devices...")

        def scan_thread():
            devices = scan_meshtastic_devices()
            self.result_queue.put(('devices_found', devices))

        threading.Thread(target=scan_thread, daemon=True).start()

    def _init_meshtastic(self, port=None):
        """Initialize Meshtastic interface in background.

        Args:
            port: Optional device path to connect to. If None, uses auto-detect.
        """
        self.status_log.add_message(f"Connecting to Meshtastic device{f' ({port})' if port else ''}...")

        def try_connect() -> bool:
            """Single connection attempt.

            Returns:
                True if the attempt reached a final outcome (success or
                permanent failure) and should not be retried. False if it hit
                a transient error and a retry may succeed.
            """
            try:
                transport = MeshtasticSerialTransport()
                transport.connect(port)

                # Get the raw interface for node listing (Stories 11.2, 11.3)
                iface = transport._iface

                # Validate we got valid device info
                node_id = None
                if hasattr(iface, 'myInfo') and iface.myInfo and hasattr(iface.myInfo, 'my_node_num'):
                    node_id = f"!{iface.myInfo.my_node_num:x}"

                if not node_id or not node_id.startswith('!'):
                    # Interface created but device info invalid - likely no device connected
                    try:
                        transport.disconnect()
                    except Exception:
                        pass
                    self.result_queue.put(('connection_failed', "Could not retrieve device info. Ensure device is connected.", None))
                    return True

                node_name = get_own_node_name(iface)
                self.result_queue.put(('connected', iface, node_id, node_name))
                # Also store transport for later use in sending
                self.result_queue.put(('transport_ready', transport))
                return True

            except ImportError:
                self.result_queue.put(('connection_error', "Meshtastic library not installed", None))
                return True
            except Exception as e:
                error_msg = str(e)
                # Check if this is a transient error from the Meshtastic library/OS
                # still releasing or initializing the port (e.g. right after a
                # previous device on this or another port was disconnected).
                is_transient = any(x in error_msg.lower() for x in [
                    'resource temporarily unavailable',
                    'busy',
                ])
                if is_transient:
                    # Show as info message - device is still initializing
                    self.result_queue.put(('connection_initializing', error_msg, None))
                    return False

                # Provide more helpful error messages for common cases
                if "No Meshtastic" in error_msg or "No serial" in error_msg:
                    error_msg = "No Meshtastic device found"
                elif "Permission denied" in error_msg:
                    error_msg = f"Permission denied accessing {port or 'device'}"
                elif "could not open port" in error_msg.lower():
                    error_msg = f"Could not open port {port or '(auto-detect)'}"
                self.result_queue.put(('connection_error', error_msg, None))
                return True

        def init_thread():
            for attempt in range(CONNECT_MAX_ATTEMPTS):
                if try_connect():
                    return
                if attempt < CONNECT_MAX_ATTEMPTS - 1:
                    time.sleep(CONNECT_RETRY_DELAY_SECONDS)
            self.result_queue.put((
                'connection_error',
                f"Device at {port or '(auto-detect)'} did not become ready "
                f"after {CONNECT_MAX_ATTEMPTS} attempts",
                None,
            ))

        threading.Thread(target=init_thread, daemon=True).start()

    def _disconnect_device(self):
        """Disconnect current Meshtastic interface and reset connection status."""
        if self.transport:
            # Disconnect transport in background thread to avoid blocking main thread
            transport_to_close = self.transport
            self.transport = None
            self.iface = None

            def close_thread():
                try:
                    transport_to_close.disconnect()
                except Exception as e:
                    self.result_queue.put(('log', f'Warning: error disconnecting device: {e}', logging.WARNING))

            threading.Thread(target=close_thread, daemon=True).start()
        elif self.iface:
            # Fallback for backward compatibility
            iface_to_close = self.iface
            self.iface = None

            def close_thread():
                try:
                    iface_to_close.close()
                except Exception as e:
                    self.result_queue.put(('log', f'Warning: error disconnecting device: {e}', logging.WARNING))

            threading.Thread(target=close_thread, daemon=True).start()
        self.connection_label.text = STATE_DISCONNECTED.text
        self.connection_label.color = STATE_DISCONNECTED.color
        # Clear known nodes
        self.known_nodes = []
        self.node_spinner.values = [MANUAL_ENTRY_TEXT]
        self.node_spinner.text = MANUAL_ENTRY_TEXT

    def on_device_selected(self, spinner, text):
        """Handle device selection from dropdown."""
        if text in (NO_DEVICES_TEXT, SCANNING_TEXT, SELECT_DEVICE_TEXT, ''):
            return

        self._disconnect_device()
        self._init_meshtastic(port=text)

    def on_refresh_devices(self, instance):
        """Handle refresh button press to rescan devices."""
        self._disconnect_device()
        self._scan_devices()

    def on_node_selected(self, spinner, text):
        """Handle node selection from dropdown."""
        if text == MANUAL_ENTRY_TEXT:
            # Clear input for fresh manual entry
            self.dest_input.text = ''
            return
        if text in (NO_NODES_TEXT, ''):
            return

        # Find the node ID from the formatted display text
        for node in self.known_nodes:
            if format_node_display(node) == text:
                self.dest_input.text = node['id']
                break

    def on_refresh_nodes(self, instance):
        """Handle refresh button press to update known nodes list."""
        self._update_known_nodes()

    def _update_known_nodes(self):
        """Update the known nodes dropdown from the connected interface."""
        if not self.iface:
            self.node_spinner.values = [NO_NODES_TEXT]
            self.node_spinner.text = NO_NODES_TEXT
            self.known_nodes = []
            return

        nodes = get_known_nodes(self.iface)
        self.known_nodes = nodes

        if not nodes:
            self.node_spinner.values = [MANUAL_ENTRY_TEXT, NO_NODES_TEXT]
            self.node_spinner.text = MANUAL_ENTRY_TEXT
        else:
            # Format nodes for display and add manual entry option
            formatted_nodes = [format_node_display(n) for n in nodes]
            self.node_spinner.values = [MANUAL_ENTRY_TEXT] + formatted_nodes
            self.node_spinner.text = MANUAL_ENTRY_TEXT
            self.status_log.add_message(f"Found {len(nodes)} known node(s)", COLOR_SUCCESS)

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
        # Handle devices_found specially since it needs spinner access
        if result[0] == 'devices_found':
            devices = result[1]
            if devices:
                self.device_spinner.values = devices
                if len(devices) == 1:
                    # Auto-select and connect to single device
                    self.device_spinner.text = devices[0]
                    self.status_log.add_message(f"Found 1 device: {devices[0]}", COLOR_SUCCESS)
                    self._init_meshtastic(port=devices[0])
                else:
                    # Multiple devices - don't connect, let user choose.
                    # Use a placeholder distinct from every real device path
                    # (rather than devices[0]) so that selecting the first
                    # device in the list still registers as a text change and
                    # fires on_device_selected - Kivy Spinner only dispatches
                    # its text event when the value actually changes.
                    self.device_spinner.unbind(text=self.on_device_selected)
                    self.device_spinner.text = SELECT_DEVICE_TEXT
                    self.device_spinner.bind(text=self.on_device_selected)
                    self.status_log.add_message(f"Found {len(devices)} devices - select one to connect", COLOR_WARNING)
            else:
                self.device_spinner.values = [NO_DEVICES_TEXT]
                self.device_spinner.text = NO_DEVICES_TEXT
                self.status_log.add_message("No Meshtastic devices found", COLOR_ERROR)
            return

        # Handle transport_ready specially (store transport, don't process as normal result)
        if result[0] == 'transport_ready':
            self.transport = result[1]
            return

        action = process_result(result)

        # Apply connection label updates
        if action.connection_text is not None:
            self.connection_label.text = action.connection_text
        if action.connection_color is not None:
            self.connection_label.color = action.connection_color

        # Store interface if provided
        if action.store_iface is not None:
            self.iface = action.store_iface

        # Add log messages first (before _update_known_nodes which also logs)
        for msg, color in action.log_messages:
            self.status_log.add_message(msg, color)

        # Fetch known nodes AFTER connection success message is logged
        if action.store_iface is not None:
            self._update_known_nodes()

        # Handle state changes
        if action.stop_sending:
            self.send_btn.disabled = False
            self.abort_btn.disabled = True
            self._set_controls_enabled(True)  # Re-enable input controls

        # Show popups
        if action.show_success_popup is not None:
            self._show_success_popup(action.show_success_popup)

    def _set_controls_enabled(self, enabled: bool):
        """Enable or disable input controls during transaction send.

        Args:
            enabled: True to enable controls, False to disable them.

        Controls affected:
            - device_spinner: Device selection dropdown
            - refresh_btn: Device scan button
            - node_spinner: Known nodes dropdown
            - dest_input: Destination input field
            - refresh_nodes_btn: Node scan button
            - tx_input: Transaction hex input field
            - dry_run_toggle: Dry run toggle button
            - example_btn: Load Hex Example button
        """
        self.device_spinner.disabled = not enabled
        self.refresh_btn.disabled = not enabled
        self.node_spinner.disabled = not enabled
        self.dest_input.disabled = not enabled
        self.refresh_nodes_btn.disabled = not enabled
        self.tx_input.disabled = not enabled
        self.dry_run_toggle.disabled = not enabled
        self.example_btn.disabled = not enabled

    def on_send_pressed(self, instance):
        """Handle send button press."""
        dest = self.dest_input.text.strip()
        tx_hex = self.tx_input.text.strip().replace('\n', '').replace(' ', '')
        dry_run = self.dry_run_toggle.state == 'down'

        # Validation (dry_run skips Meshtastic connection check)
        own_node_id = get_own_node_id(self.iface)
        error = validate_send_inputs(dest, tx_hex, bool(self.iface), dry_run, own_node_id=own_node_id)
        if error:
            self.status_log.add_message(f"Error: {error}", COLOR_ERROR)
            if error == "Meshtastic not connected":
                self._init_meshtastic()
            return

        # Start sending
        self.send_btn.disabled = True
        self.abort_btn.disabled = False
        self._set_controls_enabled(False)  # Disable input controls during send
        self.status_log.clear()
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
        """Send transaction in background thread using TransactionSender."""
        try:
            if dry_run:
                # For dry run, show a preview of how the transaction would be chunked
                self._run_preview(tx_hex)
            else:
                # Create sender and send transaction
                sender = TransactionSender(self.transport)
                self._active_sender = sender

                def on_chunk_sending(chunk_num, total, attempt, wire_format):
                    self.result_queue.put(('chunk_sending', chunk_num, total, attempt))
                    self.result_queue.put(('wire_sent', wire_format))

                def on_progress(chunk_num, total):
                    self.result_queue.put(('progress', chunk_num, total))

                def on_response_received(message_text):
                    self.result_queue.put(('wire_received', message_text))

                result = sender.send_transaction(
                    tx_hex, dest,
                    on_progress=on_progress,
                    on_chunk_sending=on_chunk_sending,
                    on_response_received=on_response_received,
                )
                self.result_queue.put(('send_result', result))

        except Exception as e:
            self.result_queue.put(('error', str(e)))
        finally:
            self._active_sender = None

    def _run_preview(self, tx_hex):
        """Show a preview of how the transaction would be chunked."""
        try:
            preview = create_preview(tx_hex)
            self.result_queue.put(('log', f'Preview: {preview.total_chunks} chunk(s)', logging.INFO))
            for chunk in preview.chunks:
                # Show truncated wire format for readability
                display = chunk.wire_format[:60] + '...' if len(chunk.wire_format) > 60 else chunk.wire_format
                self.result_queue.put(('log', f'  Chunk {chunk.chunk_num}/{chunk.total_chunks}: {display}', logging.DEBUG))
            self.result_queue.put(('send_result', SendResult(
                success=False,
                session_id=preview.session_id,
                error='Preview only — not sent'
            )))
        except Exception as e:
            self.result_queue.put(('send_result', SendResult(
                success=False,
                session_id='',
                error=f'Preview failed: {str(e)}'
            )))

    def _show_success_popup(self, txid):
        """Show success popup with TXID."""
        # Create content with dark background
        content = BoxLayout(orientation='vertical', padding=30, spacing=15)
        with content.canvas.before:
            Color(*COLOR_BG)
            self._popup_bg = Rectangle(pos=content.pos, size=content.size)
        content.bind(pos=lambda inst, val: setattr(self._popup_bg, 'pos', val))
        content.bind(size=lambda inst, val: setattr(self._popup_bg, 'size', val))

        # Top spacer for space between popup top and content
        content.add_widget(Widget(size_hint_y=None, height=15))

        # Success title in green
        content.add_widget(Label(
            text='Transaction Sent!',
            font_size=32,
            bold=True,
            color=COLOR_SUCCESS,
            size_hint_y=None,
            height=50,
        ))

        # TXID label
        content.add_widget(Label(
            text='TXID:',
            font_size=24,
            color=(0.7, 0.7, 0.7, 1),
            size_hint_y=None,
            height=35,
        ))

        # TXID value in white (larger font, wrapping enabled)
        content.add_widget(Label(
            text=txid,
            font_size=24,
            color=COLOR_SECUNDARY,
            text_size=(380, None),
            size_hint_y=None,
            height=70,
            halign='center',
        ))

        # Spacer
        content.add_widget(Widget(size_hint_y=None, height=20))

        # Button column with Copy and OK buttons
        btn_row = BoxLayout(orientation='vertical', size_hint_y=None, height=110, spacing=10)

        # Copy button
        copy_btn = Button(
            text='Copy',
            background_color=COLOR_SECUNDARY,
            background_normal='',
            color=(0, 0, 0, 1),  # Black text
            bold=True,
            font_size=24,
        )

        def on_copy(instance):
            Clipboard.copy(txid)
            instance.text = 'Copied!'
            Clock.schedule_once(lambda dt: setattr(instance, 'text', 'Copy'), 1.5)

        copy_btn.bind(on_press=on_copy)
        btn_row.add_widget(copy_btn)

        # OK button styled like app buttons
        ok_btn = create_popup_button('OK', primary=True)
        btn_row.add_widget(ok_btn)

        content.add_widget(btn_row)

        # Calculate popup size based on content
        content_height = sum(child.height for child in content.children)
        padding_height = content.padding[1] + content.padding[3] if len(content.padding) == 4 else content.padding * 2
        spacing_height = content.spacing * (len(content.children) - 1)
        popup_height = content_height + padding_height + spacing_height
        # Width based on TXID text_size (380) + horizontal padding (30 * 2)
        popup_width = 440

        popup = Popup(
            title='',
            content=content,
            size_hint=(None, None),
            size=(popup_width, popup_height),
            auto_dismiss=True,
            separator_height=0,
            background_color=COLOR_BG,
            background='',
        )
        ok_btn.bind(on_press=popup.dismiss)
        popup.open()

    def on_load_example(self, instance):
        """Load example transaction hex."""
        self.tx_input.text = EXAMPLE_RAW_TX
        self.status_log.add_message("Loaded example transaction hex")

    def on_abort_pressed(self, instance):
        """Handle abort button press."""
        if self._active_sender:
            self._active_sender.abort()
            self.result_queue.put(('log', 'Abort requested...', logging.WARNING))
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
            except Exception:
                pass


def main():
    """Entry point for GUI."""
    BTCMeshApp().run()


if __name__ == '__main__':
    main()
