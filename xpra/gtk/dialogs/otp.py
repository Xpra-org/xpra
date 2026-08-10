#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.exit_codes import ExitCode
from xpra.gtk.css_overrides import add_screen_css
from xpra.gtk.dialogs.common_style import (
    add_style_class, load_common_style, style_actions, style_body, style_button, style_window,
)
from xpra.gtk.window import add_close_accel
from xpra.gtk.util import quit_on_signals, gtk_main
from xpra.os_util import gi_import
from xpra.log import Logger
from xpra.util.env import envbool
from xpra.util.thread import check_main_thread

Gtk = gi_import("Gtk")
Gdk = gi_import("Gdk")
GLib = gi_import("GLib")

log = Logger("auth")

SHOW = envbool("XPRA_OTP_SHOW", True)

CSS = b"""
.otp-window .otp-code {
    font-family: 'monospace';
    font-size: 36px;
    padding: 12px 18px;
    border-radius: 10px;
    border: 1px solid alpha(@theme_fg_color, 0.12);
    background-color: alpha(@theme_fg_color, 0.04);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}

.otp-window progressbar {
    margin-top: 4px;
}
"""

_css_loaded = False


def load_otp_css() -> None:
    global _css_loaded
    if not _css_loaded:
        load_common_style()
        add_screen_css(CSS)
        _css_loaded = True


class OTPDialog(Gtk.Window):
    def __init__(self, otp: str, lifetime: int = 30):
        check_main_thread()
        super().__init__(title="One-Time Password")
        self.set_default_size(420, 200)
        load_otp_css()
        style_window(self, "otp-window")
        self.lifetime = lifetime
        self.remaining = lifetime
        self.otp = otp
        self.revealed = SHOW

        add_close_accel(self, Gtk.main_quit)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        style_body(main_box)
        self.add(main_box)

        # Top title and subtitle
        title = Gtk.Label()
        title.set_text("Authentication code")
        add_style_class(title, "xpra-dialog-title")
        title.set_halign(Gtk.Align.START)
        main_box.pack_start(title, False, False, 0)

        subtitle = Gtk.Label(label="Use this code to complete your sign-in.")
        subtitle.set_halign(Gtk.Align.START)
        add_style_class(subtitle, "xpra-subtitle")
        main_box.pack_start(subtitle, False, False, 0)

        # OTP display area
        otp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        otp_box.set_halign(Gtk.Align.CENTER)
        main_box.pack_start(otp_box, True, True, 0)

        self.otp_label = Gtk.Label()
        self.otp_label.set_markup(self._masked_otp(self.otp))
        add_style_class(self.otp_label, "otp-code")
        self.otp_label.set_selectable(True)
        otp_box.pack_start(self.otp_label, True, True, 20)

        controls_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        otp_box.pack_start(controls_box, False, False, 0)

        # Reveal/hide toggle
        self.reveal_button = Gtk.Button()
        style_button(self.reveal_button)
        self._set_reveal_icon()
        self.reveal_button.set_tooltip_text("Show code")
        self.reveal_button.connect("clicked", self.on_reveal_clicked)
        self.reveal_button.set_size_request(48, 48)
        controls_box.pack_start(self.reveal_button, False, False, 0)

        # Copy button
        copy_button = Gtk.Button.new_from_icon_name("edit-copy", Gtk.IconSize.BUTTON)
        style_button(copy_button)
        copy_button.set_tooltip_text("Copy code to clipboard")
        copy_button.connect("clicked", self.on_copy_clicked)
        copy_button.set_size_request(48, 48)
        controls_box.pack_start(copy_button, False, False, 0)

        # Progress + time remaining
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_fraction(1.0)
        main_box.pack_start(self.progress, False, False, 0)

        # Footer actions
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        style_actions(footer)
        main_box.pack_start(footer, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        style_button(close_btn)
        close_btn.connect("clicked", lambda w: self.close())
        footer.pack_start(close_btn, False, False, 0)

        # Start timer
        GLib.timeout_add_seconds(1, self._tick)

        self.connect("destroy", Gtk.main_quit)
        self.show_all()

    def _masked_otp(self, otp: str) -> str:
        if self.revealed:
            display = otp
        else:
            display = "•" * len(otp)
        # markup to increase tracking/letter spacing
        return f"<span font='Monospace 28'>{display}</span>"

    def _set_reveal_icon(self):
        icon_name = "view-visible" if not self.revealed else "view-hidden"
        # fallback to stock label if icon isn't available
        if Gtk.IconTheme.get_default().has_icon(icon_name):
            image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
            self.reveal_button.set_image(image)
            self.reveal_button.set_always_show_image(True)
        else:
            self.reveal_button.set_label("Show" if not self.revealed else "Hide")

    def on_reveal_clicked(self, _):
        self.revealed = not self.revealed
        self._set_reveal_icon()
        self.otp_label.set_markup(self._masked_otp(self.otp))
        self.reveal_button.set_tooltip_text("Hide code" if self.revealed else "Show code")

    def on_copy_clicked(self, _):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self.otp, -1)
        clipboard.store()
        # provide visual feedback briefly
        prev_label = self.reveal_button.get_tooltip_text()
        self.reveal_button.set_tooltip_text("Copied!")
        GLib.timeout_add_seconds(2, lambda: (self.reveal_button.set_tooltip_text(prev_label) or False))

    def _tick(self) -> bool:
        self.remaining -= 1
        if self.remaining < 0:
            self.progress.set_fraction(0.0)
            self.progress.set_text("Expired")
            self.otp_label.set_markup("<span font='Monospace 20'>— expired —</span>")
            return False  # stop ticking

        fraction = self.remaining / float(self.lifetime)
        self.progress.set_fraction(fraction)
        self.progress.set_text(f"{self.remaining}s remaining")
        # subtly update otp label color if close to expiry
        if self.remaining <= 5:
            ctx = self.otp_label.get_style_context()
            ctx.add_class("xpra-muted")
        return True


def main(args: list[str]) -> int:
    if not args:
        return ExitCode.NO_DATA
    otp = args[0]
    try:
        lifetime = int(args[1])
    except (ValueError, IndexError):
        lifetime = 30

    quit_on_signals("otp")
    win = OTPDialog(otp=otp, lifetime=lifetime)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.show_all()
    gtk_main()
    return ExitCode.OK


if __name__ == "__main__":
    r = main(sys.argv[1:])
    sys.exit(r)
