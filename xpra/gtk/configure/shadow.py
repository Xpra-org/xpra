# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.os_util import gi_import
from xpra.gtk.configure.common import run_gui
from xpra.util.config import update_config_env, get_config_env
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.gtk.widget import label, setfont
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("gstreamer", "util")


SHADOW_BACKENDS: dict[str, Sequence[str]] = {
    "auto": (
        "Automatic runtime detection",
        "this is the default behaviour,",
        "this option should always find a suitable capture strategy",
        "and it may choose not to use a video stream",
    ),
    "x11": (
        "X11 screen capture",
        "copies the X11 server's pixel data,",
        "this option only requires the X11 bindings",
        "incompatible with Wayland sessions, the displays with XWayland will look blank",
    ),
    "xshm": (
        "X11 screen capture via shared memory",
        "identical to `x11` but faster thanks to the XShm extension",
    ),
    "gtk": (
        "GTK screen capture",
        "performance may vary,",
        "this option is not compatible with Wayland displays",
    ),
    "nvfbc": (
        "NVIDIA® Frame Buffer Capture",
        "this requires the proprietary module and libraries",
        "if available, this provides the fastest capture possible",
        "and also supports hardware video compression",
        "this option is only available for shadowing existing X11 sessions",
    ),
    "gstreamer": (
        "GStreamer screen capture",
        "GStreamer will capture the session's contents using an operating system specific source element",
        "the pixel data will be compressed using a stream encoder",
        "eg: h264, hevc, av1, etc",
    ),
    "gdi": (
        "GDI screen capture",
        "Legacy screen capture for MS Windows,",
        "the xpra server can use mixed encodings with this capture option",
    ),
    "pipewire": (
        "GStreamer Pipewire capture",
        "GStreamer pipewire source from the RemoteDesktop interface",
        "the pixel data will be compressed using a stream encoder",
        "eg: h264, hevc, av1, etc",
        "your desktop sessions must support the 'RemoteDesktop' dbus interface",
    ),
}


def _set_labels_text(widgets, *messages):
    for i, widget in enumerate(widgets):
        if i < len(messages):
            widget.set_text(messages[i])
        else:
            widget.set_text("")


class ConfigureGUI(BaseGUIWindow):

    # so we can call check_xshm()
    from xpra.util.system import is_Wayland
    if not is_Wayland():
        from xpra.x11.gtk.display_source import init_gdk_display_source
        init_gdk_display_source()

    def __init__(self, parent: Gtk.Window | None = None):
        self.buttons: list[Gtk.CheckButton] = []
        size = (800, 554)
        super().__init__(
            "Configure Xpra's Shadow Server",
            "shadow.png",
            wm_class=("xpra-configure-shadow-gui", "Xpra Configure Shadow GUI"),
            default_size=size,
            header_bar=(False, False),
            parent=parent,
        )
        self.set_resizable(False)

    def populate(self) -> None:
        self.clear_vbox()
        self.set_box_margin()
        self.add_widget(label("Configure Xpra's Shadow Server", font="sans 20"))
        current_setting = get_config_env("XPRA_SHADOW_BACKEND")
        from xpra.platform.shadow_server import SHADOW_OPTIONS
        for backend, check in SHADOW_OPTIONS.items():
            available = True
            tooltip = ""
            try:
                if not check():
                    available = False
                    tooltip = "not available"
            except ImportError:
                available = False
                tooltip = "not installed or not available"
            details = SHADOW_BACKENDS.get(backend, ())
            if not details:
                description = backend
                tooltip = "unknown backend"
            else:
                description = details[0]
            btn = Gtk.CheckButton(label=description)
            btn.set_tooltip_text(tooltip)
            btn.set_sensitive(available)
            btn.set_active(available and backend == current_setting)
            btn.shadow_backend = backend
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
        confirm_btn = Gtk.Button.new_with_label("Confirm")
        confirm_btn.connect("clicked", self.save_shadow)
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

    def save_shadow(self, *_args) -> None:
        active = [button for button in self.buttons if button.get_active()]
        assert len(active) == 1
        setting = active[0].shadow_backend.lower()
        log.info(f"saving XPRA_SHADOW_BACKEND={setting}")
        update_config_env("XPRA_SHADOW_BACKEND", setting)
        self.dismiss()


def main(_args) -> int:
    return run_gui(ConfigureGUI)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
