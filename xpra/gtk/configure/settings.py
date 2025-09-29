# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.configure.common import run_gui
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.util.config import update_config_attribute, with_config
from xpra.gtk.widget import label
from xpra.os_util import gi_import, OSX, WIN32
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")

SETTINGS = [
    ("Splash", "Show the splash screen on launch", "splash", ("yes", "no", "auto")),
    ("Header Bar", "Show windows using the custom header bar", "headerbar", ("yes", "no", "auto")),
    ("Border", "Show a custom window border", "border", ("", "no", "auto", "red:10")),
    ("Modal Windows", "Honour modal windows", "modal-windows", ("yes", "no")),
    ("Reconnect", "Automatically re-connect to the server", "reconnect", ("yes", "no")),
]
if OSX:
    SETTINGS.append(
        ("Swap Keys", "Swap the command and control keys", "swap-keys", ("yes", "no"))
    )
if OSX or WIN32:
    SETTINGS.append(
        ("Remote Clipboard", "Remote clipboard selection to be synchronized with", "remote-clipboard",
         ("CLIPBOARD", "PRIMARY", "SECONDARY"))
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
        self.settings_combos: dict[str, Gtk.ComboBoxText] = {}
        super().__init__(
            "Configure Xpra Settings",
            "gears.png",
            wm_class=("xpra-configure-settings-gui", "Xpra Configure Settings GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        self.add_widget(label("Configure Xpra Settings", font="sans 20"))
        self.add_text_lines((
            "",
        ))
        grid = Gtk.Grid()
        grid.set_margin_start(20)
        grid.set_margin_end(20)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)
        for i, (name, description, setting, options) in enumerate(SETTINGS):
            grid.attach(plabel(name, "", True), 0, i, 1, 1)
            grid.attach(plabel(description, "", True, font="sans 10"), 1, i, 1, 1)
            combo = Gtk.ComboBoxText()
            grid.attach(combo, 2, i, 1, 1)
            self.settings_combos[setting] = (combo, options)
        self.show_all()
        with_config(self.configure_switches)

    def configure_switches(self, config) -> bool:
        log(f"configure_switches({config})")
        for setting, cdata in self.settings_combos.items():
            combo, options = cdata
            config_value = getattr(config, setting.replace("-", "_")) or "auto"
            log(f"{setting}={config_value!r}")
            for index, value in enumerate(options):
                if not value and config_value:
                    value = config_value
                combo.append_text(value)
                matches = config_value == value
                if value in TRUE_OPTIONS:
                    matches |= str(config_value).lower() in TRUE_OPTIONS
                if value in FALSE_OPTIONS:
                    matches |= str(config_value).lower() in FALSE_OPTIONS
                combo.set_active(matches)
            combo.connect("changed", self.setting_changed, setting)
        return False

    @staticmethod
    def setting_changed(widget, setting: str) -> None:
        value = widget.get_active_text()
        log("setting_changed %s=%s", setting, value)
        update_config_attribute(setting, value)


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
