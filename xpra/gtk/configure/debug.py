# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Sequence

from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.configure.common import run_gui
from xpra.util.config import parse_user_config_file, save_user_config_file, with_config
from xpra.gtk.dialogs.debug import make_category_widgets
from xpra.gtk.widget import label
from xpra.os_util import gi_import
from xpra.log import Logger, STRUCT_KNOWN_FILTERS, KNOWN_FILTERS

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def category_toggled(btn, category: str) -> None:
    active = btn.get_active()
    log("category_toggled(%s, %r) active=%s", btn, category, active)
    config = parse_user_config_file()
    debug = []
    if "debug" in config:
        dval = config["debug"]
        if isinstance(dval, str):
            debug = [x.strip() for x in dval.split(",") if x.strip()]
        else:
            assert isinstance(dval, Sequence)
            debug = list(dval)
    if active:
        if category in debug or "all" in debug:
            return
        debug.append(category)
    else:
        if "all" in debug:
            debug = [x for x in KNOWN_FILTERS if x != category]
        elif category not in debug:
            return
        else:
            debug.remove(category)
    config["debug"] = ",".join(debug)
    save_user_config_file(config)


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.category_widgets = {}
        super().__init__(
            "Configure Debug Logging",
            "bugs.png",
            wm_class=("xpra-configure-debug-gui", "Xpra Configure Debug GUI"),
            default_size=(640, 500),
            header_bar=(False, False),
            parent=parent,
        )

    def populate(self) -> None:
        self.clear_vbox()
        self.add_widget(label("Configure Xpra's Debug Logging", font="sans 20"))
        vbox = Gtk.VBox(homogeneous=False, spacing=0)
        vbox.set_spacing(15)
        expanders, widgets = make_category_widgets(groups=STRUCT_KNOWN_FILTERS, enabled=set(), sensitive=False,
                                                   toggled=category_toggled)
        self.category_widgets = widgets
        for exp in expanders:
            vbox.pack_start(exp, True, True, 0)
        self.add_widget(vbox)
        self.show_all()
        with_config(self.configure_widgets)

    def configure_widgets(self, config) -> bool:
        log("configure_widgets: %s (%s)", config.debug, type(config.debug))
        debug = [x.strip() for x in config.debug.split(",") if x.strip()]
        for category, widget in self.category_widgets.items():
            widget.set_sensitive(True)
            widget.set_active(category in debug or "all" in debug)
        return False


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
