# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.scripts.config import str_to_bool
from xpra.gtk.configure.common import run_gui
from xpra.util.config import update_config_attribute, with_config
from xpra.gtk.widget import label
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")

FEATURES = (
    ("Audio", "Audio forwarding: speaker and microphone", "xpra.audio"),
    ("Video", "Video codecs: h264, vpx, etc", "xpra.codecs.vpx"),
    # ("Webcam", "Webcam forwarding", "xpra.codecs.v4l2"),
    ("System Tray", "System tray forwarding", "xpra.client"),
    ("File transfer", "Upload and download of files to and from the server", "xpra.net"),
    ("Printing", "Printer forwarding to the client's printer", "xpra.net"),
    ("Clipboard", "Copy & Paste to and from the server", "xpra.clipboard"),
    ("Notifications", "Notifications forwarding", "xpra.notifications"),
    ("Windows", "Windows forwarding", "xpra.client.gtk3"),
    # ("Splash", "Show the splash screen GUI", "xpra.gtk.dialogs.splash")
    # ("Readonly", "Prevent any keyboard or pointer events from being forwarded", "xpra.client.gtk3"),
)


def plabel(text, tooltip="", sensitive=False, font="sans 12") -> Gtk.Label:
    lbl = label(text, tooltip=tooltip, font=font)
    lbl.set_hexpand(False)
    lbl.set_halign(Gtk.Align.START)
    lbl.set_margin_start(5)
    lbl.set_margin_end(5)
    lbl.set_sensitive(sensitive)
    return lbl


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.subsystem_switch: dict[str, Gtk.Switch] = {}
        super().__init__(
            "Configure Xpra's Features",
            "features.png",
            wm_class=("xpra-configure-features-gui", "Xpra Configure Features GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        self.add_widget(label("Configure Xpra's Features", font="sans 20"))
        self.add_text_lines((
            "Turning off subsystems can save memory,",
            "improve security by reducing the attack surface,",
            "and also make xpra start and connect faster",
            "",
        ))

        grid = Gtk.Grid()
        grid.set_margin_start(20)
        grid.set_margin_end(20)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)

        for i, (subsystem, description, module) in enumerate(FEATURES):
            import importlib
            try:
                found = bool(importlib.import_module(module))
                tooltip = ""
            except ImportError as e:
                found = False
                tooltip = f"this feature is missing: {e}"
            grid.attach(plabel(subsystem, tooltip, found), 0, i, 1, 1)
            grid.attach(plabel(description, tooltip, found, font="sans 10"), 1, i, 1, 1)
            switch = Gtk.Switch()
            switch.set_sensitive(False)
            grid.attach(switch, 2, i, 1, 1)
            if found:
                sub = subsystem.lower().replace(" ", "-")
                self.subsystem_switch[sub] = switch
        self.show_all()
        with_config(self.configure_switches)

    def configure_switches(self, defaults) -> bool:
        for subsystem, switch in self.subsystem_switch.items():
            value = getattr(defaults, subsystem.replace("-", "_"), None)
            log(f"configure_switches: {subsystem}={value}")
            enabled = str_to_bool(value, False)
            switch.set_sensitive(True)
            switch.set_state(enabled)
            switch.connect("state-set", self.toggle_subsystem, subsystem)
        return False

    @staticmethod
    def toggle_subsystem(_widget, state, subsystem: str) -> None:
        update_config_attribute(subsystem, bool(state))


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
