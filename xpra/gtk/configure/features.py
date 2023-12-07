# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.scripts.config import parse_bool
from xpra.gtk.configure.common import update_config_attribute, with_config
from xpra.gtk.widget import label
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.subsystem_switch = {}
        super().__init__(
            "Configure Xpra's Features",
            "features.png",
            wm_class=("xpra-configure-features-gui", "Xpra Configure Features GUI"),
            default_size=(640, 500),
            header_bar=(True, False),
            parent=parent,
        )

    def populate(self):
        self.clear_vbox()
        self.add_widget(label("Configure Xpra's Features", font="sans 20"))
        lines = (
            "Turning off subsystems can save memory,",
            "improve security by reducing the attack surface,",
            "and also make xpra start and connect faster",
            "",
        )
        text = "\n".join(lines)
        lbl = label(text, font="Sans 14")
        lbl.set_line_wrap(True)
        self.add_widget(lbl)

        grid = Gtk.Grid()
        grid.set_margin_start(40)
        grid.set_margin_end(40)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)

        for i, (subsystem, description) in enumerate(
                {
                    "Audio" : "Audio forwarding: speaker and microphone",
                    "Video" : "Video codecs: h264, vpx, etc",
                    # "Webcam", "Remote Logging",
                    "System Tray" : "System tray forwarding",
                    "Clipboard" : "Copy & Paste to and from the server",
                    "Notifications" : "Notifications forwarding",
                    "Windows" : "Windows forwarding",
                }.items()
        ):
            sub = subsystem.lower().replace(" ", "_")
            lbl = label(subsystem, tooltip=description)
            lbl.set_hexpand(True)
            grid.attach(lbl, 0, i, 1, 1)
            switch = Gtk.Switch()
            switch.set_sensitive(False)
            switch.connect("state-set", self.toggle_subsystem, sub)
            grid.attach(switch, 1, i, 1, 1)
            self.subsystem_switch[sub] = switch
        self.show_all()
        with_config(self.configure_switches)

    def configure_switches(self, defaults):
        for subsystem, switch in self.subsystem_switch.items():
            value = getattr(defaults, subsystem, None)
            log(f"configure_switches: {subsystem}={value}")
            enabled = parse_bool(subsystem, value, False)
            switch.set_sensitive(True)
            switch.set_state(enabled)
            switch.connect("state-set", self.toggle_subsystem, subsystem)
        return False

    @staticmethod
    def toggle_subsystem(widget, state, subsystem):
        update_config_attribute(subsystem, state)


def main(_args) -> int:
    from xpra.gtk.configure.main import run_gui
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
