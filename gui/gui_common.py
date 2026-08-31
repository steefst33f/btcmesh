#!/usr/bin/env python3
"""
BTCMesh GUI Common Components - Shared UI elements and utilities for
both client and server GUIs.

This module provides reusable Kivy widgets, color constants, and helper
functions to maintain visual consistency across BTCMesh applications.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import get_color_from_hex

from core.device_scan import format_device_display
from core.meshtastic_utils import probe_device_identity as probe_meshtastic_device_identity
from core.meshcore_utils import probe_device_identity as probe_meshcore_device_identity


# Issue 61: paths currently being connected to by an in-flight scan
# probe, device-selection fetch, Send, or Start Server action - guards
# against two of these racing the same physical serial port
# concurrently (e.g. a background scan still mid-probe on a device when
# the operator selects that same device and presses Send before the
# scan's own probe finishes). Confirmed real-hardware to cause
# "could not open port" failures and leave orphaned per-connection
# background tasks. Module-level/process-wide, shared by both GUIs'
# every real connect call site - should_abort's scan-generation check
# only stops a batch from *starting* a new probe, not from finishing
# one already in flight, so it alone can't prevent this.
_probing_paths_lock = threading.Lock()
_probing_paths: set = set()


def acquire_probing_path(path: str, timeout: float = 30.0) -> bool:
    """Block (polling) until `path` isn't already reserved by another
    in-flight connect elsewhere in this process, then reserve it.
    Returns True once reserved. Returns False if still held after
    `timeout` - the caller should surface a clear "device busy" error
    rather than racing a doomed concurrent connect. `timeout=0` is
    non-blocking (skip immediately if already held) - used by the scan
    loop, which shouldn't stall a whole batch waiting on one device.

    Always release with release_probing_path() in a finally, on every
    exit path (including when the caller's own connect attempt fails).
    """
    deadline = time.monotonic() + timeout
    while True:
        with _probing_paths_lock:
            if path not in _probing_paths:
                _probing_paths.add(path)
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def release_probing_path(path: str) -> None:
    """Release a path reserved via acquire_probing_path(). Safe to call
    even if the path was never actually reserved (e.g. acquire_probing_path()
    itself timed out) - discard() is a no-op when the path isn't present."""
    with _probing_paths_lock:
        _probing_paths.discard(path)


# =============================================================================
# Color Constants - Bitcoin-orange themed color scheme
# =============================================================================

COLOR_PRIMARY = get_color_from_hex('#FF6B00')    # Bitcoin orange
COLOR_SUCCESS = get_color_from_hex('#4CAF50')    # Green
COLOR_ERROR = get_color_from_hex('#F44336')      # Red
COLOR_WARNING = get_color_from_hex('#FF9800')    # Orange
COLOR_BG = get_color_from_hex('#1E1E1E')         # Dark background
COLOR_BG_LIGHT = get_color_from_hex('#2D2D2D')   # Lighter background
COLOR_SECONDARY = get_color_from_hex("#FFFFFF")  # White text
COLOR_DISCONNECTED = (0.7, 0.7, 0.7, 1)          # Gray for disconnected

# Network badge colors
COLOR_MAINNET = get_color_from_hex('#FF6B00')    # Bitcoin orange for mainnet
COLOR_TESTNET = get_color_from_hex('#2196F3')    # Blue for testnet
COLOR_SIGNET = get_color_from_hex('#9C27B0')     # Purple for signet


# =============================================================================
# Connection State Dataclass
# =============================================================================

@dataclass(frozen=True)
class ConnectionState:
    """Represents a connection state with display text and color.

    Attributes:
        text: The display text for the connection status
        color: The color tuple (r, g, b, a) for the status display
    """
    text: str
    color: tuple


# =============================================================================
# Helper Functions
# =============================================================================

def get_log_color(level: int, msg: str,
                  success_keywords: Optional[list] = None,
                  error_keywords: Optional[list] = None) -> Optional[Tuple]:
    """Determine the color for a log message based on level and content.

    Args:
        level: The logging level (e.g., logging.ERROR, logging.WARNING, logging.INFO)
        msg: The log message text
        success_keywords: Optional list of keywords that indicate success messages.
                         Defaults to ['successfully', 'success', 'txid:']
        error_keywords: Optional list of keywords that indicate error messages at INFO level.
                       Defaults to ['failed', 'nack', 'timed out', 'abort',
                                   'cannot', 'closing']

    Returns:
        A color tuple (r, g, b, a) or None for default color

    See project/log_color_spec.md for full categorization requirements.
    """
    if success_keywords is None:
        success_keywords = ['successfully', 'success', 'txid:']
    if error_keywords is None:
        error_keywords = ['failed', 'nack', 'timed out', 'abort',
                         'cannot', 'closing']

    # ERROR level always red
    if level >= logging.ERROR:
        return COLOR_ERROR

    # WARNING level always orange
    if level >= logging.WARNING:
        return COLOR_WARNING

    # For INFO level, check content
    msg_lower = msg.lower()

    # Check for error keywords first (more specific)
    for keyword in error_keywords:
        if keyword in msg_lower:
            return COLOR_ERROR

    # Check for success keywords
    for keyword in success_keywords:
        if keyword in msg_lower:
            return COLOR_SUCCESS

    # Default: white/none
    return None


def get_print_color(msg: str) -> Optional[Tuple]:
    """Determine the color for a print message based on content.

    Args:
        msg: The message text

    Returns:
        A color tuple (r, g, b, a) or None for default color
    """
    msg_lower = msg.lower()
    if 'error' in msg_lower or 'failed' in msg_lower or 'abort' in msg_lower:
        return COLOR_ERROR
    elif 'success' in msg_lower or 'txid' in msg_lower:
        return COLOR_SUCCESS
    return None


# =============================================================================
# Reusable Widget Components
# =============================================================================

class StatusLog(ScrollView):
    """Scrollable status/log area for displaying messages.

    A ScrollView-based widget that displays log messages with optional
    color coding. Messages auto-scroll to show the newest entry.

    Attributes:
        layout: The internal BoxLayout containing log message labels
    """

    def __init__(self, label_height: int = 25, **kwargs):
        """Initialize the StatusLog widget.

        Args:
            label_height: Height of each log message label (default 25)
            **kwargs: Additional keyword arguments passed to ScrollView
        """
        super().__init__(**kwargs)
        self._label_height = label_height
        self.layout = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            padding=5,
            spacing=2
        )
        self.layout.bind(minimum_height=self.layout.setter('height'))
        self.add_widget(self.layout)

    def add_message(self, text: str, color: Optional[Tuple] = None):
        """Add a log message with optional color.

        Args:
            text: The message text to display
            color: Optional color tuple (r, g, b, a). If None, uses white.
        """
        if color is None:
            color = COLOR_SECONDARY

        label = Label(
            text=text,
            size_hint_y=None,
            height=self._label_height,
            halign='left',
            valign='middle',
            color=color,
        )
        # Bind text_size to ScrollView width so it updates on resize
        def update_text_size(_instance, value):
            label.text_size = (value - 20, None)
        self.bind(width=update_text_size)
        # Set initial text_size (in case width is already known)
        label.text_size = (self.width - 20 if self.width > 20 else 100, None)

        # Adjust height based on text content
        label.bind(
            texture_size=lambda instance, value: setattr(
                instance, 'height', max(self._label_height, value[1] + 10)
            )
        )
        self.layout.add_widget(label)

        # Auto-scroll to bottom
        Clock.schedule_once(lambda dt: setattr(self, 'scroll_y', 0), 0.1)

    def clear(self):
        """Clear all log messages."""
        self.layout.clear_widgets()


class BusyIndicator:
    """Purely-visual busy state for a trigger button (e.g. a "Scan"
    button) - cycles the button's own text between an idle label and a
    busy message, disabling the button meanwhile so the *same* operation
    can't be triggered again concurrently.

    Deliberately never touches any *other* widget - disabling the
    trigger button itself only prevents a duplicate concurrent trigger
    of the operation it starts, a different thing from disabling e.g. a
    device/node dropdown or a text input, which would block the user
    from doing something else entirely unrelated while a background
    fetch is in flight (Issue 39 / project/plans/story_29_1.md - a user
    who already knows the device path or destination node ID shouldn't
    have to wait for a scan/fetch just to pick or type it).

    Reference-counted rather than a simple on/off flag: start()/stop()
    calls from independent, possibly-overlapping code paths (e.g. a
    device scan and the auto-selected device's own identity fetch, see
    btcmesh_client_gui.py's on_device_selected()) each get their own
    paired call, without one path's stop() restoring idle state while
    another path's work is still genuinely in flight.
    """

    _FRAME_COUNT = 4
    _INTERVAL_SECONDS = 0.4

    def __init__(self, button, idle_text: str):
        self._button = button
        self._idle_text = idle_text
        self._active_count = 0
        self._message = ''
        self._frame_index = 0
        self._event = None
        button.text = idle_text

    @property
    def active(self) -> bool:
        """Whether at least one start() is still awaiting a matching stop()."""
        return self._active_count > 0

    def start(self, message: str) -> None:
        """Register one more reason this button should show busy state."""
        self._active_count += 1
        if self._active_count == 1:
            self._message = message
            self._frame_index = 0
            self._button.text = message
            self._button.disabled = True
            self._event = Clock.schedule_interval(self._tick, self._INTERVAL_SECONDS)

    def stop(self) -> None:
        """Clear one reason this button should show busy state - only
        actually restores idle state once every start() has a matching
        stop()."""
        if self._active_count == 0:
            return
        self._active_count -= 1
        if self._active_count == 0:
            if self._event is not None:
                self._event.cancel()
                self._event = None
            self._button.text = self._idle_text
            self._button.disabled = False

    def _tick(self, _dt) -> None:
        self._frame_index = (self._frame_index + 1) % self._FRAME_COUNT
        self._button.text = self._message + '.' * self._frame_index


# =============================================================================
# Widget Factory Functions
# =============================================================================

def create_separator(color: Tuple = None, height: int = 2) -> Widget:
    """Create a horizontal separator line widget.

    Args:
        color: Color tuple for the separator. Defaults to COLOR_PRIMARY.
        height: Height of the separator in pixels. Defaults to 2.

    Returns:
        A Widget configured as a colored horizontal line.
    """
    if color is None:
        color = COLOR_PRIMARY

    separator = Widget(size_hint_y=None, height=height)
    with separator.canvas:
        Color(*color)
        rect = Rectangle(pos=separator.pos, size=separator.size)
    separator.bind(pos=lambda inst, val: setattr(rect, 'pos', val))
    separator.bind(size=lambda inst, val: setattr(rect, 'size', val))
    return separator


def create_title(text: str, font_size: int = 42) -> BoxLayout:
    """Create a styled title widget.

    Args:
        text: The title text to display
        font_size: Font size for the title. Defaults to 42.

    Returns:
        A BoxLayout containing the styled title label.
    """
    title_box = BoxLayout(size_hint_y=None, height=50, padding=15)
    title_label = Label(
        text=text,
        font_size=font_size,
        bold=True,
        color=COLOR_PRIMARY,
    )
    title_box.add_widget(title_label)
    return title_box


def create_section_label(text: str, height: int = 25) -> Label:
    """Create a section label (e.g., 'Activity Log:').

    Args:
        text: The label text
        height: Height of the label. Defaults to 25.

    Returns:
        A Label widget with left-aligned text.
    """
    label = Label(
        text=text,
        size_hint_y=None,
        height=height,
        halign='left',
    )
    label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
    return label


def create_clear_button(on_press_callback, text: str = 'Clear Log') -> Button:
    """Create a styled Clear Log button.

    Args:
        on_press_callback: Function to call when button is pressed
        text: Button text. Defaults to 'Clear Log'.

    Returns:
        A styled Button widget.
    """
    btn = Button(
        text=text,
        size_hint_y=None,
        height=40,
        background_color=COLOR_BG_LIGHT,
        background_normal='',
    )
    btn.bind(on_press=on_press_callback)
    return btn


def create_action_button(text: str, color: Tuple = None, bold: bool = True,
                            disabled: bool = False) -> Button:
    """Create a styled action button.

    Args:
        text: Button text
        color: Background color tuple. Defaults to COLOR_PRIMARY.
        bold: Whether to use bold text. Defaults to True.
        disabled: Whether button is initially disabled. Defaults to False.

    Returns:
        A styled Button widget.
    """
    if color is None:
        color = COLOR_PRIMARY

    return Button(
        text=text,
        background_color=color,
        background_normal='',
        bold=bold,
        disabled=disabled,
    )


def create_refresh_button(text: str, width: int = 90) -> Button:
    """Create a styled refresh/scan button with fixed width.

    Args:
        text: Button text.
        width: Button width in pixels. Defaults to 90.

    Returns:
        A styled Button widget with fixed width.
    """
    return Button(
        text=text,
        size_hint_x=None,
        width=width,
        background_color=COLOR_BG_LIGHT,
        background_normal='',
        font_size='14sp',
    )


def create_toggle_button(text: str, width: int = 60) -> Button:
    """Create a styled toggle button (e.g., Show/Hide for password fields).

    Args:
        text: Initial button text.
        width: Button width in pixels. Defaults to 60.

    Returns:
        A styled Button widget with fixed width.
    """
    return Button(
        text=text,
        size_hint_x=None,
        width=width,
        background_color=COLOR_BG_LIGHT,
        background_normal='',
        font_size='12sp',
    )


def create_popup_button(text: str, primary: bool = True) -> Button:
    """Create a styled button for use in popups.

    Creates a full-width button with larger font size, suitable for
    popup dialogs (e.g., Close, OK, Copy buttons).

    Args:
        text: Button text.
        primary: If True, uses COLOR_PRIMARY (orange). If False, uses COLOR_BG_LIGHT.

    Returns:
        A styled Button widget with fixed height.
    """
    return Button(
        text=text,
        size_hint_y=None,
        height=50,
        background_color=COLOR_PRIMARY if primary else COLOR_BG_LIGHT,
        background_normal='',
        bold=True,
        font_size='18sp',
    )


def create_popup_inline_button(text: str, width: int = 120) -> Button:
    """Create a styled inline button for use in popup rows.

    Creates a fixed-width button matching the style of main screen
    inline buttons (Scan, Show/Hide), suitable for inline placement
    within popup content rows (e.g., Copy TXID button).

    Args:
        text: Button text.
        width: Button width in pixels. Defaults to 120.

    Returns:
        A styled Button widget with fixed width.
    """
    return Button(
        text=text,
        size_hint_x=None,
        width=width,
        background_color=COLOR_BG_LIGHT,
        background_normal='',
        font_size='14sp',
    )


def create_status_row(label_text: str, initial_value: str = '',
                      initial_color: Tuple = None,
                      height: int = 30, bold_value: bool = False) -> Tuple[BoxLayout, Label]:
    """Create a status row with a description label and value label.

    Creates a horizontal layout with an auto-sized description label on the left
    and a flexible-width value label on the right. The description label
    automatically sizes to fit its text content. The value label can be updated
    independently to show status changes.

    Args:
        label_text: Text for the description label (e.g., 'Meshtastic:')
        initial_value: Initial text for the value label. Defaults to empty.
        initial_color: Initial color for the value label. Defaults to COLOR_SECONDARY.
        height: Height of the row in pixels. Defaults to 30.
        bold_value: Whether the value label should be bold. Defaults to False.

    Returns:
        Tuple of (container BoxLayout, value Label). The value Label can be used
        to update the status text and color.

    Example:
        row, value_label = create_status_row('Meshtastic:', 'Not connected')
        status_section.add_widget(row)
        # Later, update the status:
        value_label.text = 'Connected (!abcdef12)'
        value_label.color = COLOR_SUCCESS
    """
    if initial_color is None:
        initial_color = COLOR_SECONDARY

    row = BoxLayout(orientation='horizontal', size_hint_y=None, height=height)

    # Description label (auto-sized to fit text)
    desc_label = Label(
        text=label_text,
        size_hint_x=None,
        halign='left',
        valign='middle',
        color=COLOR_SECONDARY,
    )
    # Bind width to texture size so label auto-fits its text content (+ padding for spacing)
    desc_label.bind(texture_size=lambda inst, val: setattr(inst, 'width', val[0] + 25))
    row.add_widget(desc_label)

    # Value label (flexible width)
    value_label = Label(
        text=initial_value,
        halign='left',
        valign='middle',
        color=initial_color,
        bold=bold_value,
    )
    value_label.bind(size=value_label.setter('text_size'))
    row.add_widget(value_label)

    return row, value_label


def create_input_row(label_text: str, initial_value: str = '',
                    hint_text: str = '', height: int = 40,
                    password: bool = False, input_filter: str = None,
                    input_size_hint_x: float = 0.7) -> Tuple[BoxLayout, TextInput]:
    """Create an input row with a description label and text input field.

    Creates a horizontal layout with an auto-sized description label on the left
    and a styled TextInput on the right. The description label automatically
    sizes to fit its text content using texture_size binding.

    Args:
        label_text: Text for the description label (e.g., 'Host:', 'Password:')
        initial_value: Initial text value for the input. Defaults to empty.
        hint_text: Placeholder hint text for the input. Defaults to empty.
        height: Height of the row in pixels. Defaults to 40.
        password: Whether to mask input as password. Defaults to False.
        input_filter: Optional input filter (e.g., 'int' for numbers only).
        input_size_hint_x: Proportional width for the input field. Defaults to 0.7.

    Returns:
        Tuple of (container BoxLayout, TextInput). The TextInput can be used
        to access or modify the input value.

    Example:
        row, host_input = create_input_row('Host:', '127.0.0.1', hint_text='IP address')
        settings_section.add_widget(row)
        # Later, get the value:
        host = host_input.text.strip()
    """
    row = BoxLayout(orientation='horizontal', size_hint_y=None, height=height, spacing=5)

    # Description label (auto-sized to fit text)
    desc_label = Label(
        text=label_text,
        size_hint_x=None,
        halign='right',
        valign='middle',
        color=COLOR_SECONDARY,
    )
    # Bind width to texture size so label auto-fits its text content (+ padding for spacing)
    desc_label.bind(texture_size=lambda inst, val: setattr(inst, 'width', val[0] + 15))
    row.add_widget(desc_label)

    # Text input with consistent styling
    text_input = TextInput(
        text=initial_value,
        hint_text=hint_text,
        multiline=False,
        password=password,
        size_hint_x=input_size_hint_x,
        background_color=COLOR_BG_LIGHT,
        foreground_color=COLOR_SECONDARY,
        cursor_color=COLOR_PRIMARY,
    )
    if input_filter:
        text_input.input_filter = input_filter
    row.add_widget(text_input)

    return row, text_input


# =============================================================================
# Device Selection Helpers - shared between client and server GUIs (Story
# 27.2/27.3). Both GUIs' device dropdowns need identical mechanics: probe
# each scanned candidate for its Meshtastic identity in the background,
# dedupe entries that turn out to be the same physical device (two OS-level
# path aliases resolving to the same node ID - Issue 37), resolve a
# formatted display string back to its underlying path, and relabel the
# dropdown as identities resolve without disrupting the current selection.
# Written as plain functions operating on passed-in state (a `devices` list
# of {'path', 'node_id', 'name'} dicts) rather than bound methods, since
# neither GUI needs to share instance state with the other - see
# project/plans/story_27_1.md's "Architecture Revision" section.
# =============================================================================

def probe_devices_in_background(devices: List[dict], result_queue,
                                 skip_paths: frozenset = frozenset(),
                                 transport_name: str = "meshtastic",
                                 should_abort: Optional[Callable[[], bool]] = None) -> None:
    """Start a background thread that briefly connects to each device in
    `devices` to learn its node ID, name, firmware version, and hardware
    model (probe_device_identity() - connect, read identity, disconnect -
    dispatched by transport_name; MeshCore's probe currently always
    leaves firmware_version/hw_model None, see Issue 54), pushing
    ('device_identity', path, node_id, name, firmware_version, hw_model)
    onto result_queue for each one not in skip_paths, followed by a final
    ('device_probe_complete',) once the whole batch is done (in a
    finally, so it still fires even if a probe raises) - the only
    reliable "all done" signal a caller has, e.g. to stop a busy
    indicator (Issue 39).

    transport_name dispatch is resolved by name inside the thread body
    (not a module-level dict built once at import time) so
    unittest.mock.patch('gui.gui_common.probe_meshtastic_device_identity', ...)
    -style patching keeps working, the same way the previous single-
    transport bare call already resolved through this module's namespace.

    should_abort (Story 30.4): an optional callable the caller can use to
    invalidate an already-running batch - e.g. after the operator flips
    the transport selector while this batch (started under the previous
    transport) is still mid-flight. Checked before each device's probe;
    once it returns True, remaining devices are skipped without probing
    (real device connects, one per device, aren't cheap to let run to
    completion just to discard the result). device_probe_complete still
    always fires in the finally either way, so a caller's busy-indicator
    start()/stop() pairing (ref-counted, Issue 39) stays balanced even on
    an aborted batch.

    A path already reserved elsewhere (Issue 61 - another in-flight
    scan batch, a device-selection fetch, Send, or Start Server -
    should_abort only stops a batch from *starting* a new probe, not
    from finishing one already running) is skipped without probing and
    without a result - non-blocking, since one busy device shouldn't
    stall the whole batch; whoever already holds it will publish its own
    result when it finishes.
    """
    def probe_thread():
        try:
            for device in list(devices):
                if should_abort is not None and should_abort():
                    break
                path = device['path']
                if path in skip_paths:
                    continue
                if not acquire_probing_path(path, timeout=0):
                    continue
                try:
                    if transport_name == "meshcore":
                        identity = probe_meshcore_device_identity(path)
                    else:
                        identity = probe_meshtastic_device_identity(path)
                finally:
                    release_probing_path(path)
                result_queue.put((
                    'device_identity', path, identity.node_id, identity.name,
                    identity.firmware_version, identity.hw_model,
                ))
        finally:
            result_queue.put(('device_probe_complete',))

    threading.Thread(target=probe_thread, daemon=True).start()


def dedupe_devices_by_node_id(devices: List[dict], keep_path: str,
                               protect_path: Optional[str] = None):
    """If keep_path's device shares its node ID with another entry in
    devices, drop the duplicate - two paths resolving to the same node ID
    are provably the same physical device (Issue 37: two OS-level path
    aliases for one device). Normally keep_path (the side that was just
    authoritatively resolved - a probe result, or a live connection) wins
    and the other entry is dropped, EXCEPT protect_path is never dropped:
    if it turns out to be the duplicate (it was already known; keep_path
    resolved to the same node ID after), keep_path is the one dropped
    instead. Pass protect_path=None (the default) to disable that
    exemption entirely - no device path is ever equal to None, so nothing
    is ever protected.

    Returns (new_devices_list, removed_device_or_None). Does not mutate
    `devices` in place.
    """
    keeper = next((d for d in devices if d['path'] == keep_path), None)
    if keeper is None or not keeper['node_id']:
        return devices, None
    duplicates = [
        d for d in devices
        if d['path'] != keep_path and d['node_id'] == keeper['node_id']
    ]
    if not duplicates:
        return devices, None
    if any(d['path'] == protect_path for d in duplicates):
        removed = keeper
        new_devices = [d for d in devices if d['path'] != keep_path]
    else:
        removed = duplicates[0]
        dup_paths = {d['path'] for d in duplicates}
        new_devices = [d for d in devices if d['path'] not in dup_paths]
    return new_devices, removed


def device_path_from_display(devices: List[dict], text: str) -> str:
    """Resolve a device dropdown's display string back to its underlying
    path, mirroring the known-nodes dropdown's reverse-lookup pattern.
    Falls back to treating text as a raw path unchanged if it doesn't
    match any entry (sentinel values like "Auto-detect", or a path that
    hasn't been added to `devices` yet)."""
    for device in devices:
        if format_device_display(
            device['path'], device['node_id'], device['name'], device.get('hw_model')
        ) == text:
            return device['path']
    return text


def refresh_device_spinner_labels(spinner, devices: List[dict], selection_handler=None,
                                   extra_values=()) -> None:
    """Rebuild spinner.values from devices as identities resolve,
    preserving the currently selected device across the relabel.
    Unbinds/rebinds selection_handler around the mutation if given, so
    relabeling never fires a spurious selection event - Kivy Spinner fires
    its bound text handler on any value change, including a relabel-only
    one. Omit selection_handler for a spinner with no bound handler to
    protect (e.g. the server GUI's, which has none at all).

    extra_values are sentinel entries (e.g. "Auto-detect") that aren't in
    `devices` but must stay in the dropdown regardless - without this, the
    first identity-probe result to land would silently wipe them out, since
    spinner.values is otherwise rebuilt purely from `devices`."""
    selected_path = device_path_from_display(devices, spinner.text)

    if selection_handler is not None:
        spinner.unbind(text=selection_handler)
    spinner.values = list(extra_values) + [
        format_device_display(d['path'], d['node_id'], d['name'], d.get('hw_model'))
        for d in devices
    ]
    for device in devices:
        if device['path'] == selected_path:
            spinner.text = format_device_display(
                device['path'], device['node_id'], device['name'], device.get('hw_model')
            )
            break
    if selection_handler is not None:
        spinner.bind(text=selection_handler)
