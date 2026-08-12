# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.server.shadow.common import SHADOW_BACKENDS
from xpra.gtk.configure.common import ConfigureGUIWindow, run_gui
from xpra.util.config import update_config_env, get_config_env
from xpra.gtk.dialogs.common_style import add_style_class
from xpra.gtk.widget import label as gtk_label, setfont
from xpra.util.i18n import _
from xpra.log import Logger

Gtk = gi_import("Gtk")
GLib = gi_import("GLib")

log = Logger("util")


def label(text, *args, **kwargs):
    return gtk_label(_(text), *args, **kwargs)


def _set_labels_text(widgets, *messages):
    for i, widget in enumerate(widgets):
        if i < len(messages):
            widget.set_text(messages[i])
        else:
            widget.set_text("")


class ConfigureGUI(ConfigureGUIWindow):

    # so we can call check_xshm()
    from xpra.util.system import is_Wayland
    if not is_Wayland():
        try:
            from xpra.x11.display_source import init_display_source
            init_display_source()
        except ImportError:
            log("unable to initialize X11 display source", exc_info=True)

    def __init__(self, parent: Gtk.Window | None = None):
        self.buttons: list[Gtk.CheckButton] = []
        size = (800, 554)
        super().__init__(
            _("Configure Xpra's Shadow Server"),
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
        current_setting = get_config_env("XPRA_SHADOW_BACKEND")
        from xpra.platform.shadow_server import SHADOW_OPTIONS
        for backend, check in SHADOW_OPTIONS.items():
            available = True
            tooltip = ""
            try:
                if not check():
                    available = False
                    tooltip = "not available"
            except RuntimeError as e:
                available = False
                tooltip = "unable to initialize: %s" % e
            except ImportError:
                available = False
                tooltip = "not installed or not available"
            details = SHADOW_BACKENDS.get(backend, ())
            if not details:
                description = backend
                tooltip = "unknown backend"
            else:
                description = details[0]
            btn = Gtk.CheckButton(label=_(description))
            btn.set_tooltip_text(_(tooltip))
            btn.set_sensitive(available)
            btn.set_active(available and backend == current_setting)
            btn.shadow_backend = backend
            setfont(btn, font="sans 14")
            add_style_class(btn, "configure-option")
            self.vbox.add(btn)
            for detail in details[1:]:
                lbl = label(detail)
                lbl.set_halign(Gtk.Align.START)
                lbl.set_margin_start(32)
                lbl.set_sensitive(available)
                add_style_class(lbl, "configure-detail")
                self.vbox.add(lbl)
            self.buttons.append(btn)
        btn_box = Gtk.HBox(homogeneous=True, spacing=40)
        btn_box.set_vexpand(True)
        btn_box.set_valign(Gtk.Align.END)
        btn_box.set_halign(Gtk.Align.END)
        add_style_class(btn_box, "xpra-actions")
        self.vbox.add(btn_box)
        cancel_btn = Gtk.Button.new_with_label(_("Cancel"))
        add_style_class(cancel_btn, "xpra-action")
        cancel_btn.connect("clicked", self.dismiss)
        btn_box.add(cancel_btn)
        confirm_btn = Gtk.Button.new_with_label(_("Confirm"))
        add_style_class(confirm_btn, "xpra-action", "suggested-action")
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
