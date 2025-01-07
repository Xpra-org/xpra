# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import sys
import os.path
import subprocess
import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Gdk", "3.0")  # @UndefinedVariable
from gi.repository import Gtk, Gio  # @UnresolvedImport

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.child_reaper import getChildReaper
from xpra.gtk_common.gtk_util import (
    add_close_accel, get_icon_pixbuf,
    imagebutton,
    label,
    )
from xpra.platform.paths import get_xpra_command
from xpra.os_util import WIN32, OSX, is_X11
from xpra.log import Logger

log = Logger("client", "util")


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    creationflags = 0
    if WIN32:
        creationflags = subprocess.CREATE_NO_WINDOW  # @UndefinedVariable
    proc = subprocess.Popen(cmd, env=env, creationflags=creationflags)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


TITLE = "Xpra Toolbox"

BUTTON_GROUPS = {
    "Colors": (
        ("Squares", "Shows RGB+Grey squares in a window", "colors-plain"),
        ("Animated", "Shows RGB+Grey squares animated", "colors"),
        ("Bit Depth", "Shows color gradients and visualize bit depth clipping", "colors-gradient"),
    ),
    "Transparency and Rendering": (
        ("Circle", "Shows a semi-opaque circle in a transparent window", "transparent-window"),
        ("RGB Squares", "RGB+Black shaded squares in a transparent window", "transparent-colors"),
        ("OpenGL", "OpenGL window - transparent on some platforms", "opengl"),
    ),
    "Widgets": (
        ("Text Entry", "Simple text entry widget", "text-entry"),
        ("File Selector", "Open the file selector widget", "file-chooser"),
        ("Header Bar", "Window with a custom header bar", "header-bar"),
    ),
    "Events": (
        ("Grabs", "Test keyboard and pointer grabs", "grabs"),
        ("Clicks", "Double and triple click events", "clicks"),
        ("Focus", "Shows window focus events", "window-focus"),
    ),
    "Windows": (
        ("States", "Toggle various window attributes", "window-states"),
        ("Title", "Update the window title", "window-title"),
        ("Opacity", "Change window opacity", "window-opacity"),
        ("Transient", "Show transient windows", "window-transient"),
        ("Override Redirect", "Shows an override redirect window", "window-overrideredirect"),
    ),
    "Geometry": (
        ("Size constraints", "Specify window geometry size constraints", "window-geometry-hints"),
        ("Move-Resize", "Initiate move resize from application", "initiate-moveresize"),
    ),
    "Keyboard and Clipboard": (
        ("Keyboard", "Keyboard event viewer", "view-keyboard"),
        ("Clipboard", "Clipboard event viewer", "view-clipboard"),
    ),
    "Misc": (
        ("Tray", "Show a system tray icon", "tray"),
        ("Font Rendering", "Render characters with and without anti-aliasing", "fontrendering"),
        ("Bell", "Test system bell", "bell"),
        ("Cursors", "Show named cursors", "cursors"),
    ),
}


class ToolboxGUI(Gtk.Window):

    def __init__(self, title=TITLE):
        self.exit_code = 0
        self.start_session = None
        super().__init__()
        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_wmclass("xpra-toolbox", "Xpra-Toolbox")

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = title
        button = Gtk.Button()
        icon = Gio.ThemedIcon(name="help-about")
        image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
        button.add(image)
        button.set_tooltip_text("About")
        button.connect("clicked", self.show_about)
        hb.add(button)
        hb.show_all()
        self.set_titlebar(hb)

        icon_name = "applications-utilities"
        self.set_icon_name(icon_name)
        icon_theme = Gtk.IconTheme.get_default()
        try:
            pixbuf = icon_theme.load_icon(icon_name, 96, 0)
        except Exception:
            pixbuf = get_icon_pixbuf("xpra")
        if pixbuf:
            self.set_icon(pixbuf)
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)

        self.vbox = Gtk.VBox(homogeneous=False, spacing=10)
        self.add(self.vbox)

        def addhbox(blabel, buttons):
            self.vbox.add(label(blabel, font="sans 14"))
            hbox = Gtk.HBox(homogeneous=False, spacing=10)
            self.vbox.add(hbox)
            for button in buttons:
                if button:
                    hbox.add(self.button(*button))

        for category, button_defs in BUTTON_GROUPS.items():
            addhbox(f"{category}:", button_defs)
        self.vbox.show_all()

    @staticmethod
    def label(text):
        return label(text, font="sans 14")

    @staticmethod
    def button(label_str, tooltip, example="", enabled=True) -> Gtk.Button:
        log(f"{label_str} : {example}")

        def cb(_btn) -> None:
            cmd = get_xpra_command() + ["example", example]
            proc = exec_command(cmd)
            getChildReaper().add_process(proc, label_str, cmd, ignore=True, forget=True)

        ib = imagebutton(label_str, None,
                         tooltip, clicked_callback=cb,
                         icon_size=48)
        ib.set_sensitive(enabled)
        return ib

    def quit(self, *args):
        log("quit%s", args)
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    @staticmethod
    def show_about(*_args):
        from xpra.gtk_common.about import about
        about()


def main(args) -> int:
    if len(args) == 1:
        # find a matching script or label:
        match = args[0].lower()
        return run_example(match)

    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready, set_default_icon
    with program_context("Xpra-Toolbox", TITLE):
        enable_color()

        set_default_icon("toolbox.png")
        init()

        gui = ToolboxGUI()
        register_os_signals(gui.app_signal, TITLE)
        ready()
        gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":
    r = main(sys.argv[1:])
    sys.exit(r)
