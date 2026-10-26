# This file is part of Xpra.
# Copyright (C) 2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk.configure.common import ConfigureGUIWindow, run_gui
from xpra.gtk.dialogs.common_style import add_style_class
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.util.config import update_config_attribute, with_config
from xpra.gtk.widget import label as gtk_label
from xpra.util.i18n import _
from xpra.os_util import gi_import, OSX, WIN32
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def label(text, tooltip="", **kwargs):
    return gtk_label(_(text), tooltip=_(tooltip), **kwargs)


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
# `clipboard=all` synchronizes all the selections the platform can handle,
# and not just the default one, see `xpra.client.subsystem.clipboard`:
ALL_SELECTIONS = "all"
if OSX or WIN32:
    # these platforms only have a single clipboard,
    # so choose which remote selection(s) it is synchronized with,
    # turning the clipboard on or off is done with `xpra configure features`:
    SETTINGS.append(
        ("Remote Clipboard", "Remote clipboard selection to be synchronized with", "remote-clipboard",
         ("CLIPBOARD", "PRIMARY", "SECONDARY", (ALL_SELECTIONS, "PRIMARY and CLIPBOARD")))
    )


def get_remote_clipboard(config) -> str:
    # `PRIMARY and CLIPBOARD` is the `clipboard=all` mode:
    if (config.clipboard or "").lower() == ALL_SELECTIONS:
        return ALL_SELECTIONS
    return config.remote_clipboard or "CLIPBOARD"


def set_remote_clipboard(value: str, clipboard: str) -> None:
    if value == ALL_SELECTIONS:
        # the local `PRIMARY` and `CLIPBOARD` map to the same remote selections:
        update_config_attribute("clipboard", ALL_SELECTIONS)
        update_config_attribute("remote-clipboard", "CLIPBOARD")
        return
    if clipboard.lower() == ALL_SELECTIONS:
        update_config_attribute("clipboard", "auto")
    update_config_attribute("remote-clipboard", value)


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
        self.settings_combos: dict[str, Gtk.ComboBoxText] = {}
        self.clipboard = "auto"
        super().__init__(
            _("Configure Xpra Settings"),
            "gears.png",
            wm_class=("xpra-configure-settings-gui", "Xpra Configure Settings GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        grid = Gtk.Grid()
        add_style_class(grid, "xpra-card", "configure-grid")
        grid.set_column_spacing(12)
        grid.set_row_spacing(4)
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(False)
        self.add_widget(grid)
        for i, (name, description, setting, options) in enumerate(SETTINGS):
            name_label = plabel(name, "", True)
            add_style_class(name_label, "configure-label")
            grid.attach(name_label, 0, i, 1, 1)
            description_label = plabel(description, "", True, font="sans 10")
            add_style_class(description_label, "configure-description")
            grid.attach(description_label, 1, i, 1, 1)
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
            if setting == "remote-clipboard":
                config_value = get_remote_clipboard(config)
                if str(config.clipboard).lower() in FALSE_OPTIONS:
                    combo.set_sensitive(False)
                    combo.set_tooltip_text(_("The clipboard is disabled, see `xpra configure features`"))
            log(f"{setting}={config_value!r}")
            values = []
            for index, option in enumerate(options):
                # options can be a value, or a `(value, label)` pair:
                value, text = option if isinstance(option, tuple) else (option, option)
                if not value and config_value:
                    value = text = config_value
                values.append(value)
                combo.append_text(_(text))
                matches = config_value == value
                if value in TRUE_OPTIONS:
                    matches |= str(config_value).lower() in TRUE_OPTIONS
                if value in FALSE_OPTIONS:
                    matches |= str(config_value).lower() in FALSE_OPTIONS
                if matches:
                    combo.set_active(index)
            combo.connect("changed", self.setting_changed, setting, values)
        self.clipboard = str(config.clipboard or "auto")
        return False

    def setting_changed(self, widget, setting: str, values: list[str]) -> None:
        value = values[widget.get_active()]
        log("setting_changed %s=%s", setting, value)
        if setting == "remote-clipboard":
            set_remote_clipboard(value, self.clipboard)
            self.clipboard = ALL_SELECTIONS if value == ALL_SELECTIONS else "auto"
            return
        update_config_attribute(setting, value)


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
