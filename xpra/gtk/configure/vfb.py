# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.gtk.configure.common import run_gui
from xpra.util.config import update_config_attribute, with_config
from xpra.util.io import which
from xpra.util.system import is_Debian, is_Ubuntu
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label, setfont
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("gstreamer", "util")


XDUMMY_INFO = [
    "Xdummy",
    "Xorg server with the `dummy` driver",
    "runs a full `Xorg` server",
    "supports multi-monitor virtualization and DPI emulation",
]
if is_Debian() or is_Ubuntu():
    XDUMMY_INFO.append("should not be used on Debian or Ubuntu due to severe bugs")


VFB_BACKENDS: dict[str, tuple[Sequence[str], Sequence[str]]] = {
    "auto": (
        (),
        (
            "auto",
            "Automatic runtime detection",
            "this is usually a safe option",
        ),
    ),
    "Xdummy": (
        ("Xorg", ),
        XDUMMY_INFO,
    ),
    "weston+Xwayland": (
        ("weston", "Xwayland"),
        (
            "weston + Xwayland",
            "runs Xwayland on a weston server headless backend",
            "alternative to Xdummy",
            "with more limited multi-monitor and DPI support",
        ),
    ),
    "Xvfb": (
        ("Xvfb", ),
        (
            "Xvfb",
            "traditional Xvfb virtual framebuffer",
            "It emulates a dumb framebuffer using virtual memory",
            "only requires the `Xvfb` binary installed",
            "no multi-monitor support and limited DPI emulation",
        ),
    ),
    #    "Xephyr": (
    #        ("Xephyr", ),
    #        (
    #            "Xephyr",
    #            "Launches a nested display from the current X11 server",
    #            "requires an existing X11 session",
    #            "only really useful for debugging",
    #        ),
    #    ),
}


def _set_labels_text(widgets, *messages):
    for i, widget in enumerate(widgets):
        if i < len(messages):
            widget.set_text(messages[i])
        else:
            widget.set_text("")


class ConfigureGUI(BaseGUIWindow):

    def __init__(self, parent: Gtk.Window | None = None):
        self.buttons: list[Gtk.CheckButton] = []
        size = (800, 554)
        super().__init__(
            "Configure Xpra's xvfb command",
            "monitor.png",
            wm_class=("xpra-configure-vfb-gui", "Xpra Configure vfb GUI"),
            default_size=size,
            header_bar=(False, False),
            parent=parent,
        )
        self.set_resizable(False)

    def populate(self) -> None:
        with_config(self.do_populate)

    def do_populate(self, config) -> bool:
        self.clear_vbox()
        self.set_box_margin()
        self.add_widget(label("Configure Xpra's xvfb command", font="sans 20"))

        xvfb = config.xvfb
        log(f"current {xvfb=!r}")
        for backend, defs in VFB_BACKENDS.items():
            commands, details = defs
            available = True
            tooltip = ""
            matched = backend.lower().replace(" ", "") == xvfb.lower()
            for command in commands:
                if xvfb == command:
                    matched = True
                if not which(command):
                    available = False
                    tooltip = f"{command} not found"
            description = details[0]
            btn = Gtk.CheckButton(label=description)
            btn.set_tooltip_text(tooltip)
            btn.set_sensitive(available)
            btn.set_active(available and matched)
            btn.xvfb_backend = backend
            setfont(btn, font="sans 14")
            self.vbox.add(btn)
            for detail in details[1:]:
                lbl = label(detail)
                lbl.set_halign(Gtk.Align.START)
                lbl.set_margin_start(32)
                lbl.set_sensitive(available)
                self.vbox.add(lbl)
            self.buttons.append(btn)
        btn_box = Gtk.HBox(homogeneous=True, spacing=40)
        btn_box.set_vexpand(True)
        btn_box.set_valign(Gtk.Align.END)
        self.vbox.add(btn_box)
        cancel_btn = Gtk.Button.new_with_label("Cancel")
        cancel_btn.connect("clicked", self.dismiss)
        btn_box.add(cancel_btn)
        confirm_btn = Gtk.Button.new_with_label("Save")
        confirm_btn.connect("clicked", self.save_xvfb)
        confirm_btn.set_sensitive(False)
        btn_box.add(confirm_btn)

        # only enable the confirm button once an option has been chosen,
        # and ensure that there is always one option selected
        def option_toggled(toggled_btn=None, *_args) -> None:
            if toggled_btn and toggled_btn.get_active():
                for button in self.buttons:
                    if button != toggled_btn:
                        button.set_active(False)
            else:
                if not any(button.get_active() for button in self.buttons):
                    self.buttons[0].set_active(True)
            confirm_btn.set_sensitive(any(button.get_active() for button in self.buttons))

        for btn in self.buttons:
            btn.connect("toggled", option_toggled)
        option_toggled()
        self.vbox.show_all()
        return False

    def save_xvfb(self, *_args) -> None:
        active = [button for button in self.buttons if button.get_active()]
        assert len(active) == 1
        xvfb = active[0].xvfb_backend
        log.info(f"saving {xvfb=!r}")
        update_config_attribute("xvfb", xvfb)
        self.dismiss()


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
