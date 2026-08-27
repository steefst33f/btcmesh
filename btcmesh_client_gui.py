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
from gui.gui_common import (
    # Colors
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_WARNING,
    COLOR_BG,
    COLOR_BG_LIGHT,
    COLOR_SECONDARY,
    COLOR_DISCONNECTED,
    # Classes
    ConnectionState,
    StatusLog,
    BusyIndicator,
    # Functions
    get_log_color,
    create_separator,
    create_section_label,
    create_title,
    create_action_button,
    create_clear_button,
    create_refresh_button,
    create_popup_button,
    # Device-selection mechanics (Story 27.2/27.3 - identical between this
    # GUI and the server GUI, see project/plans/story_27_1.md's
    # "Architecture Revision" section)
    probe_devices_in_background,
    dedupe_devices_by_node_id,
    device_path_from_display,
    refresh_device_spinner_labels,
)

# Import Meshtastic utilities from core
from core.meshtastic_utils import (
    scan_meshtastic_devices,
    get_own_node_name,
    get_known_nodes,
    format_node_display,
    format_device_display,
)

# Import transport layer
from transport.meshtastic_serial import MeshtasticSerialTransport
from transport.base import TransportConnectionError
from transport.power_control import probe_relay_board_id

# Import transaction sending logic
from client.sender import TransactionSender, SendResult, create_preview
from core.protocol import is_valid_hex

# Device selection constants
NO_DEVICES_TEXT = "No devices found"
SCANNING_TEXT = "Scanning..."
SELECT_DEVICE_TEXT = "Select a device to connect..."

# Issue 37: shown wherever a candidate is confirmed to be the Story 26.7
# relay board (probe_relay_board_id()) rather than attempting a
# Meshtastic connect that could never succeed against it - and would
# otherwise cost a full ~30s connection timeout for nothing.
RELAY_BOARD_SELECTED_MESSAGE = (
    "This is the relay board's control port, not a Meshtastic device - "
    "select a different device."
)

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

# Connection state (using ConnectionState from gui_common)
STATE_DISCONNECTED = ConnectionState('Meshtastic: Not connected', COLOR_DISCONNECTED)


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

    elif result_type == 'log':
        msg = result[1]
        level = result[2]
        color = get_log_color(level, msg)
        action.log_messages.append((msg, color))

    elif result_type == 'chunk_sending':
        chunk_num, total, attempt = result[1], result[2], result[3]
        if attempt > 1:
            msg = f'Sending chunk {chunk_num}/{total} (retry {attempt - 1})...'
        else:
            msg = f'Sending chunk {chunk_num}/{total}...'
        action.log_messages.append((msg, COLOR_PRIMARY))

    elif result_type == 'wire_sent':
        wire_format = result[1]
        action.log_messages.append((f'  -> {wire_format}', COLOR_SECONDARY))

    elif result_type == 'progress':
        chunk_num, total = result[1], result[2]
        if chunk_num == total:
            msg = f'Chunk {chunk_num}/{total} sent — waiting for broadcast...'
        else:
            msg = f'Chunk {chunk_num}/{total} sent'
        action.log_messages.append((msg, COLOR_PRIMARY))

    elif result_type == 'wire_received':
        message_text = result[1]
        action.log_messages.append((f'  <- {message_text}', COLOR_SECONDARY))

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

    elif result_type == 'error':
        error = result[1]
        action.log_messages.append((f"Error: {error}", COLOR_ERROR))
        action.stop_sending = True

    return action


def validate_send_inputs(dest: str, tx_hex: str) -> Optional[str]:
    """Validate the format-level inputs for sending a transaction, before
    any connection is attempted.

    This is a pure function that validates inputs without touching the GUI.
    Connection readiness is no longer checked here (2026-08-23 revision):
    connecting is now part of the send flow itself, not a precondition
    checked ahead of it - see project/plans/story_27_1.md's "Architecture
    Revision" section. Likewise, the self-send check ("Cannot send to your
    own node") moved to _send_transaction_thread, since the device's own
    node ID isn't known until after connecting.

    Args:
        dest: The destination node ID
        tx_hex: The raw transaction hex (already cleaned of whitespace)

    Returns:
        An error message string if validation fails, or None if inputs are valid
    """
    try:
        MeshtasticSerialTransport().validate_destination(dest)
    except ValueError as e:
        # Issue 30: the actual validation rule lives on
        # MeshtasticSerialTransport (also used by the CLI and
        # client/sender.py) - only the empty-destination message differs
        # here, to keep this GUI's existing user-facing copy unchanged.
        return "Enter destination node ID" if not dest else str(e)

    if not tx_hex:
        return "Enter transaction hex"

    if len(tx_hex) % 2 != 0:
        return "Hex must have even length"

    if not is_valid_hex(tx_hex):
        return "Invalid hex characters"

    return None


def _friendly_connect_error(port: Optional[str], exc: Exception) -> str:
    """Map a raw connect-failure exception into clearer text, shared by
    every brief background connect this file makes (the real Send
    connection, and the lighter-weight device-info/known-nodes fetches
    triggered by device selection) so they all read the same way. The
    raw text (e.g. "Timed out waiting for connection completion") reads
    like a failed Send attempt even when the user never asked to connect
    - they just selected a device - so the timeout case specifically is
    reframed as "didn't respond" rather than "connection failed"; the
    caller's own log prefix ("Could not fetch device info: ...", etc.)
    is what actually says *what* was being attempted."""
    msg = str(exc)
    if "No Meshtastic" in msg or "No serial" in msg:
        return "No Meshtastic device found"
    if "Permission denied" in msg:
        return f"Permission denied accessing {port or 'device'}"
    if "could not open port" in msg.lower():
        return f"Could not open port {port or '(auto-detect)'}"
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return (
            f"{port or 'Device'} did not respond - it may not be a "
            "Meshtastic device, or isn't responding right now"
        )
    return msg


class BTCMeshGUI(BoxLayout):
    """Main GUI widget."""

    status_text = StringProperty('Ready')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 15
        self.spacing = 20

        # transport/iface are only ever set for the duration of an active
        # send (Story 27.2 revision, 2026-08-23) - no ambient connection is
        # held while idle. See project/plans/story_27_1.md's "Architecture
        # Revision" section for why: nothing needs it before Send is
        # pressed (identity display uses its own brief probe connections),
        # and holding one open during idle browsing was the reason a
        # dedicated idle-liveness watchdog (Story 28.4) ever needed to
        # exist - itself a wedge-risk, per the rapid-reconnect-cycling
        # pattern documented in Issue 12.
        self.transport = None
        self.iface = None
        self.send_thread = None
        self.result_queue = queue.Queue()
        # Devices found by the last scan, with node IDs/names filled in as
        # background probes resolve (Story 27.2): [{'path':, 'node_id':, 'name':}]
        self.devices = []
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

        # Spinner (drop down list), full width on its own row. Picking a
        # device still doesn't connect anything for Send's sake
        # (2026-08-23 revision) - but it does trigger a brief connect to
        # refresh the known-nodes destination dropdown, since known nodes
        # are per-device and a stale list from a previously selected
        # device would be actively misleading.
        self.device_spinner = Spinner(
            text=SCANNING_TEXT,
            values=[],
            size_hint_x=1,
            size_hint_y=None,
            height=40,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
            color=COLOR_SECONDARY,
        )
        self.device_spinner.bind(text=self.on_device_selected)
        self.add_widget(self.device_spinner)

        # Scan button - also the busy indicator itself (Issue 39): reads
        # "Scan" while idle, "Scanning devices..."/"Identifying
        # devices..." while a scan/identity-probe is in flight, disabled
        # meanwhile to prevent a duplicate concurrent scan - never
        # anything else. device_spinner is untouched throughout, so an
        # already-known device can still be picked before probing
        # finishes labeling it. Full-width on its own row (rather than a
        # small fixed-width side button) since the busy text needs the
        # extra room.
        self.refresh_btn = create_refresh_button('Scan')
        self.refresh_btn.size_hint_x = 1
        self.refresh_btn.size_hint_y = None
        self.refresh_btn.height = 40
        self.refresh_btn.bind(on_press=self.on_refresh_devices)
        self.device_busy = BusyIndicator(self.refresh_btn, idle_text='Scan')
        self.add_widget(self.refresh_btn)

        # Destination input section
        self.add_widget(create_section_label('Destination Node ID:'))

        # Node selection row (Spinner + TextInput)
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
            color=COLOR_SECONDARY,
        )
        self.node_spinner.bind(text=self.on_node_selected)
        dest_selection_box.add_widget(self.node_spinner)

        # TextInput for destination (manual entry or selected from dropdown)
        self.dest_input = TextInput(
            hint_text='!node_id',
            multiline=False,
            size_hint_x=0.5,
            background_color=COLOR_BG_LIGHT,
            foreground_color=COLOR_SECONDARY,
            cursor_color=COLOR_SECONDARY,
        )
        dest_selection_box.add_widget(self.dest_input)

        self.add_widget(dest_selection_box)

        # Refresh-nodes button - also the busy indicator itself (Issue 39),
        # same pattern as the device Scan button above: "Scan" while idle,
        # "Fetching known nodes..." while in flight, disabled meanwhile to
        # prevent a duplicate concurrent fetch only. node_spinner/dest_input
        # stay fully usable throughout - a destination can still be picked
        # or typed before the fetch finishes. Full-width on its own row for
        # the same reason as the device Scan button.
        self.refresh_nodes_btn = create_refresh_button('Scan')
        self.refresh_nodes_btn.size_hint_x = 1
        self.refresh_nodes_btn.size_hint_y = None
        self.refresh_nodes_btn.height = 40
        self.refresh_nodes_btn.bind(on_press=self.on_refresh_nodes)
        self.nodes_busy = BusyIndicator(self.refresh_nodes_btn, idle_text='Scan')
        self.add_widget(self.refresh_nodes_btn)

        # TX Hex input
        self.add_widget(create_section_label('Raw Transaction Hex:'))
        self.tx_input = TextInput(
            hint_text='Paste raw transaction hex here...',
            multiline=True,
            size_hint_y=None,
            height=180,
            background_color=COLOR_BG_LIGHT,
            foreground_color=COLOR_SECONDARY,
            cursor_color=COLOR_SECONDARY,
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
        self.device_busy.start("Scanning devices...")

        def scan_thread():
            devices = scan_meshtastic_devices()
            self.result_queue.put(('devices_found', devices))

        threading.Thread(target=scan_thread, daemon=True).start()

    def _connect_with_retry(self, port):
        """Connect to the Meshtastic device with retries, blocking until
        success or final failure - synchronous, called only from the send
        thread (2026-08-23 revision: connecting is now part of Send, not a
        standalone ambient action - see project/plans/story_27_1.md's
        "Architecture Revision" section). Mirrors
        btcmesh_client_cli.py's run_send() connect step, adapted to push
        progress as log messages for this GUI's activity log instead of
        printing to stdout.

        Returns the connected MeshtasticSerialTransport.
        Raises TransportConnectionError on final failure.
        """
        if port and probe_relay_board_id(port):
            raise TransportConnectionError(RELAY_BOARD_SELECTED_MESSAGE)

        self.result_queue.put((
            'log', f"Connecting to Meshtastic device{f' ({port})' if port else ''}...", logging.INFO
        ))

        last_error = None
        for attempt in range(CONNECT_MAX_ATTEMPTS):
            try:
                transport = MeshtasticSerialTransport()
                transport.connect(port)
                # Issue 32: local_node_id is always correctly zero-padded;
                # transport.connect() already guarantees it's set by the
                # time it returns without raising.
                if not transport.local_node_id:
                    transport.disconnect()
                    raise TransportConnectionError(
                        "Could not retrieve device info. Ensure device is connected."
                    )
                return transport
            except TransportConnectionError as e:
                last_error = e
                error_msg = str(e)
                # A freshly enumerated serial port (or one just released by
                # a prior disconnect) can transiently fail to open for a
                # moment - retry before giving up.
                is_transient = any(x in error_msg.lower() for x in [
                    'resource temporarily unavailable',
                    'busy',
                ])
                if is_transient and attempt < CONNECT_MAX_ATTEMPTS - 1:
                    self.result_queue.put((
                        'log', "Device is initializing, please wait...", logging.WARNING
                    ))
                    time.sleep(CONNECT_RETRY_DELAY_SECONDS)
                    continue
                break

        raise TransportConnectionError(
            _friendly_connect_error(port, last_error)
        ) from last_error

    def on_refresh_devices(self, instance):
        """Handle refresh button press to rescan devices."""
        self._scan_devices()

    def on_device_selected(self, spinner, text):
        """Handle device selection: one brief connect that fetches both
        the newly-selected device's identity (for labeling/dedup) and its
        known nodes (for the destination dropdown), then disconnects.
        Does not hold a persistent connection - Send still does its own
        separate connect (2026-08-23 revision, see
        project/plans/story_27_1.md's "Fix: Known-Nodes Staleness on
        Device Selection" section). Known nodes are per-device, so
        without this a stale list from a previously selected device would
        be actively misleading - a node reachable from one physical
        device isn't necessarily reachable from another."""
        if text in (NO_DEVICES_TEXT, SCANNING_TEXT, SELECT_DEVICE_TEXT, ''):
            return

        # Clear immediately rather than waiting for the fetch to finish -
        # otherwise the previous device's known nodes stay visible (still
        # wrong, just briefly) until the new list arrives.
        self._update_known_nodes([])

        path = device_path_from_display(self.devices, text)
        self.status_log.add_message("Fetching device info and known nodes...")
        self.device_busy.start("Fetching device info...")
        self.nodes_busy.start("Fetching known nodes...")

        def fetch_thread():
            # Wrapped in try/finally so device_and_nodes_fetch_complete
            # always fires exactly once, on every exit path (relay-board
            # guard, connect failure, or success) - the busy indicators'
            # stop() calls depend on it (Issue 39).
            try:
                if probe_relay_board_id(path):
                    self.result_queue.put(('log', RELAY_BOARD_SELECTED_MESSAGE, logging.WARNING))
                    return
                try:
                    transport = MeshtasticSerialTransport()
                    transport.connect(path)
                except TransportConnectionError as e:
                    self.result_queue.put((
                        'log', f"Could not fetch device info: {_friendly_connect_error(path, e)}", logging.ERROR
                    ))
                    return
                try:
                    node_id = transport.local_node_id
                    name = get_own_node_name(transport._iface)
                    self.result_queue.put(('device_identity', path, node_id, name))
                    nodes = get_known_nodes(transport._iface)
                    self.result_queue.put(('known_nodes_fetched', nodes))
                finally:
                    transport.disconnect()
            finally:
                self.result_queue.put(('device_and_nodes_fetch_complete',))

        threading.Thread(target=fetch_thread, daemon=True).start()

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
        """Handle refresh button press: briefly connect to the currently
        selected device, fetch its known nodes, then disconnect (Story
        11.2, revised 2026-08-23 - no longer reads an ambient connection;
        see project/plans/story_27_1.md's "Architecture Revision"
        section)."""
        port = device_path_from_display(self.devices, self.device_spinner.text)
        self.status_log.add_message("Fetching known nodes...")
        self.nodes_busy.start("Fetching known nodes...")

        def fetch_thread():
            # Wrapped in try/finally so known_nodes_fetch_complete always
            # fires exactly once, on every exit path - nodes_busy.stop()
            # depends on it (Issue 39).
            try:
                if probe_relay_board_id(port):
                    self.result_queue.put(('log', RELAY_BOARD_SELECTED_MESSAGE, logging.WARNING))
                    return
                try:
                    transport = MeshtasticSerialTransport()
                    transport.connect(port)
                except TransportConnectionError as e:
                    self.result_queue.put((
                        'log', f"Could not fetch known nodes: {_friendly_connect_error(port, e)}", logging.ERROR
                    ))
                    return
                try:
                    nodes = get_known_nodes(transport._iface)
                    self.result_queue.put(('known_nodes_fetched', nodes))
                finally:
                    transport.disconnect()
            finally:
                self.result_queue.put(('known_nodes_fetch_complete',))

        threading.Thread(target=fetch_thread, daemon=True).start()

    def _update_known_nodes(self, nodes):
        """Apply a fetched known-nodes list to the destination dropdown."""
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
                self.devices = [{'path': p, 'node_id': None, 'name': None} for p in devices]
                self.device_spinner.values = [
                    format_device_display(d['path'], d['node_id'], d['name']) for d in self.devices
                ]
                if len(devices) == 1:
                    # Auto-select (not auto-connect - 2026-08-23 revision,
                    # see project/plans/story_27_1.md's "Architecture
                    # Revision" section) the lone device. No separate
                    # background probe needed here - setting .text fires
                    # on_device_selected (bound below in _build_ui), whose
                    # own brief connect fetches identity for free, the
                    # same role the live Send connection played before
                    # this revision (see the "Fix: Known-Nodes Staleness"
                    # section for why probing the same sole device twice
                    # at once would just race itself).
                    self.device_spinner.text = devices[0]
                    self.status_log.add_message(f"Found device: {devices[0]}", COLOR_SUCCESS)
                else:
                    # Multiple devices - SELECT_DEVICE_TEXT is a sentinel
                    # on_device_selected ignores, so setting it here
                    # doesn't trigger a fetch; probe every candidate in
                    # the background instead, for labeling. Once the user
                    # actually picks one, on_device_selected takes over.
                    self.device_spinner.text = SELECT_DEVICE_TEXT
                    # No specific count stated here (unlike the single-
                    # device case above) - the raw scan count can still
                    # drop once probing resolves names/node IDs and dedup
                    # collapses aliases of the same physical device
                    # (Issue 37), possibly down to just one; "device(s)"
                    # stays accurate either way. The dropdown itself is
                    # the real, already-visible source of truth for
                    # "how many."
                    self.status_log.add_message("Device(s) found - select one to connect", COLOR_WARNING)
                    # Own start() paired with the device_probe_complete
                    # handler's stop() - independent of the scan's own
                    # start()/stop() pair below (Issue 39, ref-counted).
                    self.device_busy.start("Identifying devices...")
                    probe_devices_in_background(self.devices, self.result_queue)
            else:
                self.devices = []
                self.device_spinner.values = [NO_DEVICES_TEXT]
                self.device_spinner.text = NO_DEVICES_TEXT
                self.status_log.add_message("No Meshtastic devices found", COLOR_ERROR)
            # The scan itself (device_busy.start() in _scan_devices()) is
            # done either way - a follow-on probe_devices_in_background()
            # call above owns its own device_busy.start()/stop() pair
            # independently (ref-counted, see BusyIndicator).
            self.device_busy.stop()
            return

        # Issue 39: the whole multi-device identity-probe batch just
        # finished (or errored partway through) - pairs with
        # probe_devices_in_background()'s device_busy.start() call above.
        if result[0] == 'device_probe_complete':
            self.device_busy.stop()
            return

        # Issue 39: on_device_selected()'s combined identity+known-nodes
        # fetch just finished (or errored) - pairs with its own
        # device_busy.start()/nodes_busy.start() calls.
        if result[0] == 'device_and_nodes_fetch_complete':
            self.device_busy.stop()
            self.nodes_busy.stop()
            return

        # Issue 39: on_refresh_nodes()'s fetch just finished (or errored) -
        # pairs with its own nodes_busy.start() call.
        if result[0] == 'known_nodes_fetch_complete':
            self.nodes_busy.stop()
            return

        # Background identity-probe result for one device (Story 27.2,
        # extended by Issue 37's node-name work)
        if result[0] == 'device_identity':
            path, node_id, name = result[1], result[2], result[3]
            for device in self.devices:
                if device['path'] == path:
                    device['node_id'], device['name'] = node_id, name
                    break
            if node_id:
                self.devices, _removed = dedupe_devices_by_node_id(self.devices, keep_path=path)
            refresh_device_spinner_labels(
                self.device_spinner, self.devices, selection_handler=self.on_device_selected
            )
            return

        if result[0] == 'known_nodes_fetched':
            self._update_known_nodes(result[1])
            return

        if result[0] == 'disconnected':
            self.connection_label.text = STATE_DISCONNECTED.text
            self.connection_label.color = STATE_DISCONNECTED.color
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

        # Add log messages
        for msg, color in action.log_messages:
            self.status_log.add_message(msg, color)

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

        error = validate_send_inputs(dest, tx_hex)
        if error:
            self.status_log.add_message(f"Error: {error}", COLOR_ERROR)
            return

        # Resolve which physical device to use now, while the dropdown's
        # current selection is still on the main thread - connecting
        # itself happens inside the send thread below (2026-08-23
        # revision: connecting is part of Send, not a standalone ambient
        # action - see project/plans/story_27_1.md's "Architecture
        # Revision" section).
        port = device_path_from_display(self.devices, self.device_spinner.text)

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
            args=(dest, tx_hex, dry_run, port),
            daemon=True
        )
        self.send_thread.start()

    def _send_transaction_thread(self, dest, tx_hex, dry_run, port):
        """Connect (unless dry-run), send the transaction, then disconnect
        - mirrors btcmesh_client_cli.py's run_send() (connect, send,
        disconnect in a finally), just wrapped in this file's existing
        background-thread + result_queue pattern."""
        if dry_run:
            # No connection needed at all for a preview.
            self._run_preview(tx_hex)
            return

        try:
            transport = self._connect_with_retry(port)
        except TransportConnectionError as e:
            self.result_queue.put(('error', str(e)))
            return

        self.transport = transport
        self.iface = transport._iface
        try:
            node_id = transport.local_node_id
            node_name = get_own_node_name(self.iface)
            self.result_queue.put(('connected', self.iface, node_id, node_name))

            if dest.lower() == node_id.lower():
                self.result_queue.put(('error', "Cannot send to your own node"))
                return

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
            self.transport.disconnect()
            self.transport = None
            self.iface = None
            self.result_queue.put(('disconnected',))

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
            color=COLOR_SECONDARY,
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
            background_color=COLOR_SECONDARY,
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
        """Cleanup on app close - only matters if a send is active when
        the window closes, since no connection is otherwise held open."""
        if hasattr(self.root, 'transport') and self.root.transport:
            try:
                self.root.transport.disconnect()
            except Exception:
                pass


def main():
    """Entry point for GUI."""
    BTCMeshApp().run()


if __name__ == '__main__':
    main()
