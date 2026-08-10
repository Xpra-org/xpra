# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.util.parsing import str_to_bool
from xpra.gtk.configure.common import ConfigureGUIWindow, run_gui
from xpra.gtk.dialogs.common_style import add_style_class
from xpra.util.config import update_config_attribute, with_config
from xpra.gtk.widget import label as gtk_label
from xpra.util.i18n import _
from xpra.os_util import gi_import
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def label(text, tooltip="", **kwargs):
    return gtk_label(_(text), tooltip=_(tooltip), **kwargs)


FEATURES = (
    ("audio.png", "Audio", "Audio forwarding: speaker and microphone", "xpra.audio"),
    ("video.png", "Video", "Video codecs: h264, vpx, etc", "xpra.codecs.vpx"),
    # ("webcam.png", "Webcam", "Webcam forwarding", "xpra.webcam"),
    ("up.png", "System Tray", "System tray forwarding", "xpra.client"),
    ("directory.png", "File transfer", "Upload and download of files to and from the server", "xpra.net"),
    ("printer.png", "Printing", "Printer forwarding to the client's printer", "xpra.net"),
    ("clipboard.png", "Clipboard", "Copy & Paste to and from the server", "xpra.clipboard"),
    ("information.png", "Notifications", "Notification forwarding", "xpra.notification"),
    ("windows.png", "Windows", "Window forwarding", "xpra.client.gtk3"),
    # ("MMap", "Fast shared memory transfers", "xpra.net.mmap"),
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


class ConfigureGUI(ConfigureGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.subsystem_switch: dict[str, Gtk.Switch] = {}
        super().__init__(
            _("Configure Xpra's Features"),
            "features.png",
            wm_class=("xpra-configure-features-gui", "Xpra Configure Features GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        self.add_text_lines((
            "Turning off subsystems can save memory,",
            "improve security by reducing the attack surface,",
            "and also make xpra start and connect faster",
            "",
        ))

        grid = Gtk.Grid()
        add_style_class(grid, "xpra-card", "configure-grid")
        grid.set_column_spacing(10)
        grid.set_row_spacing(2)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)

        for i, (icon_name, subsystem, description, module) in enumerate(FEATURES):
            icon = get_icon_pixbuf(icon_name)
            if icon:
                image = Gtk.Image.new_from_pixbuf(icon)
                add_style_class(image, "configure-icon")
                grid.attach(image, 0, i, 1, 1)
            import importlib
            try:
                found = bool(importlib.import_module(module))
                tooltip = ""
            except ImportError as e:
                found = False
                tooltip = _("this feature is missing: %s") % e
            name_label = plabel(subsystem, tooltip, found)
            add_style_class(name_label, "configure-label")
            grid.attach(name_label, 1, i, 1, 1)
            description_label = plabel(description, tooltip, found, font="sans 10")
            add_style_class(description_label, "configure-description")
            grid.attach(description_label, 2, i, 1, 1)
            switch = Gtk.Switch()
            switch.set_sensitive(False)
            grid.attach(switch, 3, i, 1, 1)
            if found:
                sub = subsystem.lower().replace(" ", "-")
                self.subsystem_switch[sub] = switch
        self.show_all()
        with_config(self.configure_switches)

    def configure_switches(self, defaults) -> bool:
        log(f"configure_switches({defaults})")
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
        log("toggle_subsystem %s=%s", subsystem, bool(state))
        update_config_attribute(subsystem, bool(state))


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
