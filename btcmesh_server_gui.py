#!/usr/bin/env python3
"""
BTCMesh Server GUI - Kivy-based graphical interface for running and monitoring
the BTCMesh relay server.

This GUI wraps the btcmesh_server module, providing visual status displays,
activity logging, and server controls.
"""
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
from kivy.core.window import Window
from kivy.properties import BooleanProperty

# Import shared GUI components
from gui_common import (
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
