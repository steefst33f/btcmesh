#!/usr/bin/env python3
"""
BTCMesh Server GUI - Kivy-based graphical interface for running and monitoring
the BTCMesh relay server.

This GUI wraps the btcmesh_server module, providing visual status displays,
activity logging, and server controls.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, BooleanProperty
from kivy.utils import get_color_from_hex


# Set window size for desktop
Window.size = (550, 700)

# Colors - matching client GUI theme
COLOR_PRIMARY = get_color_from_hex('#FF6B00')  # Bitcoin orange
COLOR_SUCCESS = get_color_from_hex('#4CAF50')  # Green
COLOR_ERROR = get_color_from_hex('#F44336')    # Red
COLOR_WARNING = get_color_from_hex('#FF9800')  # Orange
COLOR_BG = get_color_from_hex('#1E1E1E')       # Dark background
COLOR_BG_LIGHT = get_color_from_hex('#2D2D2D') # Lighter background
COLOR_SECUNDARY = get_color_from_hex("#FFFFFF")
COLOR_DISCONNECTED = (0.7, 0.7, 0.7, 1)


@dataclass(frozen=True)
class ConnectionState:
    """Represents a connection state with display text and color."""
    text: str
    color: tuple


# Meshtastic connection states
STATE_MESHTASTIC_DISCONNECTED = ConnectionState('Meshtastic: Not connected', COLOR_DISCONNECTED)
STATE_MESHTASTIC_CONNECTED = ConnectionState('Meshtastic: Connected', COLOR_SUCCESS)
STATE_MESHTASTIC_FAILED = ConnectionState('Meshtastic: Connection failed', COLOR_ERROR)

# Bitcoin RPC connection states
STATE_RPC_DISCONNECTED = ConnectionState('Bitcoin RPC: Not connected', COLOR_DISCONNECTED)
STATE_RPC_CONNECTED = ConnectionState('Bitcoin RPC: Connected', COLOR_SUCCESS)
STATE_RPC_FAILED = ConnectionState('Bitcoin RPC: Connection failed', COLOR_ERROR)


def get_log_color(level: int, msg: str) -> Optional[tuple]:
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
    elif 'success' in msg.lower() or 'txid' in msg.lower() or 'broadcast' in msg.lower():
        return COLOR_SUCCESS
    return None


class StatusLog(ScrollView):
    """Scrollable activity/log area for server events."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', size_hint_y=None, padding=5, spacing=2)
        self.layout.bind(minimum_height=self.layout.setter('height'))
        self.add_widget(self.layout)

    def add_message(self, text: str, color: tuple = None):
        """Add a message to the log.

        Args:
            text: The message text to display
            color: Optional color tuple (r, g, b, a). If None, uses white.
        """
        if color is None:
            color = COLOR_SECUNDARY

        label = Label(
            text=text,
            size_hint_y=None,
            height=30,
            halign='left',
            valign='middle',
            color=color
        )
        label.bind(size=label.setter('text_size'))
        self.layout.add_widget(label)

        # Auto-scroll to bottom
        Clock.schedule_once(lambda dt: self.scroll_to(label), 0.1)

    def clear(self):
        """Clear all messages from the log."""
        self.layout.clear_widgets()


class BTCMeshServerGUI(BoxLayout):
    """Main server GUI widget."""

    is_running = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 15
        self.spacing = 20

        # Set background color
        with self.canvas.before:
            Color(*COLOR_BG)
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self._update_rect, pos=self._update_rect)

        self._build_ui()

    def _update_rect(self, *args):
        """Update background rectangle on resize."""
        self.rect.pos = self.pos
        self.rect.size = self.size

    def _create_separator(self) -> Widget:
        """Create an orange horizontal separator line.

        Returns:
            A Widget configured as an orange separator line.
        """
        separator = Widget(size_hint_y=None, height=2)
        with separator.canvas:
            Color(*COLOR_PRIMARY)
            rect = Rectangle(pos=separator.pos, size=separator.size)
        separator.bind(pos=lambda inst, val: setattr(rect, 'pos', val))
        separator.bind(size=lambda inst, val: setattr(rect, 'size', val))
        return separator

    def _build_ui(self):
        """Build the GUI layout."""
        # Title
        title_box = BoxLayout(size_hint_y=None, height=50, padding=15)
        title_label = Label(
            text='BTCMesh Relay Server',
            font_size=42,
            bold=True,
            color=COLOR_PRIMARY,
        )
        title_box.add_widget(title_label)
        self.add_widget(title_box)

        # Orange separator line after title
        self.add_widget(self._create_separator())

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
        self.add_widget(self._create_separator())

        # Server controls
        controls_section = BoxLayout(orientation='horizontal', size_hint_y=None, height=50, spacing=10)

        self.start_btn = Button(
            text='Start Server',
            background_color=COLOR_PRIMARY,
            background_normal='',
            bold=True,
        )
        self.start_btn.bind(on_press=self.on_start_pressed)
        controls_section.add_widget(self.start_btn)

        self.stop_btn = Button(
            text='Stop Server',
            background_color=COLOR_ERROR,
            background_normal='',
            bold=True,
            disabled=True
        )
        self.stop_btn.bind(on_press=self.on_stop_pressed)
        controls_section.add_widget(self.stop_btn)

        self.add_widget(controls_section)

        # # Orange separator line after controls
        # self.add_widget(self._create_separator())

        # Activity log section
        log_label = Label(
            text='Activity Log:',
            size_hint_y=None,
            height=25,
            halign='left',
        )
        log_label.bind(width=lambda instance, value: setattr(instance, 'text_size', (value, None)))
        self.add_widget(log_label)

        # Status log (scrollable)
        self.status_log = StatusLog(size_hint_y=1)
        self.add_widget(self.status_log)

        # Clear log button
        self.clear_btn = Button(
            text='Clear Log',
            size_hint_y=None,
            height=40,
            background_color=COLOR_BG_LIGHT,
            background_normal='',
        )
        self.clear_btn.bind(on_press=self.on_clear_pressed)
        self.add_widget(self.clear_btn)

        # Initial log message
        self.status_log.add_message("Server GUI initialized. Click 'Start Server' to begin.", COLOR_PRIMARY)

    def on_start_pressed(self, instance):
        """Handle Start Server button press."""
        self.status_log.add_message("Starting server...", COLOR_WARNING)
        # TODO: Story 15.2 - Implement actual server start
        self.is_running = True
        self.start_btn.disabled = True
        self.stop_btn.disabled = False

    def on_stop_pressed(self, instance):
        """Handle Stop Server button press."""
        self.status_log.add_message("Stopping server...", COLOR_WARNING)
        # TODO: Story 15.2 - Implement actual server stop
        self.is_running = False
        self.start_btn.disabled = False
        self.stop_btn.disabled = True

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
