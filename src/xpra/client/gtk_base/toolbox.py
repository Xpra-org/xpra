# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import sys
import os.path
import subprocess
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GdkPixbuf, Gio

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    imagebutton,
    label,
    )
from xpra.platform.paths import get_icon_dir, get_python_execfile_command
from xpra.os_util import WIN32, is_X11
from xpra.log import Logger

log = Logger("client", "util")


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    creationflags = 0
    if WIN32:
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(cmd, env=env, creationflags=creationflags)
    log("exec_command(%s)=%s", cmd, proc)
    return proc

def get_pixbuf(icon_name):
    icon_filename = os.path.join(get_icon_dir(), icon_name)
    if os.path.exists(icon_filename):
        return GdkPixbuf.Pixbuf.new_from_file(icon_filename)
    return None


class ToolboxGUI(Gtk.Window):

    def __init__(self, title="Xpra Toolbox"):
        self.exit_code = 0
        self.start_session = None
        Gtk.Window.__init__(self)
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
            pixbuf = get_pixbuf("xpra")
        if pixbuf:
            self.set_icon(pixbuf)
        add_close_accel(self, self.quit)
        self.connect("delete_event", self.quit)

        self.vbox = Gtk.VBox(homogeneous=False, spacing=10)
        self.add(self.vbox)

        epath = "example/"
        cpath = "../"
        gpath = "../../gtk_common/"

        def addhbox(blabel, buttons):
            self.vbox.add(self.label(blabel))
            hbox = Gtk.HBox(homogeneous=False, spacing=10)
            self.vbox.add(hbox)
            for button in buttons:
                hbox.add(self.button(*button))

        addhbox("Colors:", (
            ("Squares", "Shows RGB+Grey squares in a window", epath+"colors_plain.py"),
            ("Animated", "Shows RGB+Grey squares animated", epath+"colors.py"),
            ("Bit Depth", "Shows color gradients and visualize bit depth clipping", epath+"colors_gradient.py"),
            ))
        addhbox("Transparency and Rendering", (
            ("Circle", "Shows a semi-opaque circle in a transparent window", epath+"transparent_window.py"),
            ("RGB Squares", "RGB+Black shaded squares in a transparent window", epath+"transparent_colors.py"),
            ("OpenGL", "OpenGL window - transparent on some platforms", cpath+"gl/window_backend.py"),
            ))
        addhbox("Widgets:", (
            ("Text Entry", "Simple text entry widget", epath+"text_entry.py"),
            ("File Selector", "Open the file selector widget", epath+"file_chooser.py"),
            ("Header Bar", "Window with a custom header bar", epath+"header_bar.py"),
            ))
        addhbox("Events:", (
            ("Grabs", "Test keyboard and pointer grabs", epath+"grabs.py"),
            ("Clicks", "Double and triple click events", epath+"clicks.py"),
            ("Focus", "Shows window focus events", epath+"window_focus.py"),
            ))
        addhbox("Windows:", (
            ("States", "Toggle various window attributes", epath+"window_states.py"),
            ("Title", "Update the window title", epath+"window_title.py"),
            ("Opacity", "Change window opacity", epath+"window_opacity.py"),
            ("Transient", "Show transient windows", epath+"window_transient.py"),
            ("Override Redirect", "Shows an override redirect window", epath+"window_overrideredirect.py"),
            ))
        if is_X11():
            addhbox("X11:", (
                ("Move-Resize", "Initiate move resize from application", epath+"initiate_moveresize.py"),
                ))
        addhbox("Keyboard and Clipboard:", (
            ("Keyboard", "Keyboard event viewer", gpath+"gtk_view_keyboard.py"),
            ("Clipboard", "Clipboard event viewer", gpath+"gtk_view_clipboard.py"),
            ))
        addhbox("Misc:", (
                ("Tray", "Show a system tray icon", epath+"tray.py"),
                ("Font Rendering", "Render characters with and without anti-aliasing", epath+"fontrendering.py"),
                ("Bell", "Test system bell", epath+"bell.py"),
                ("Cursors", "Show named cursors", epath+"cursors.py"),
                ))
        self.vbox.show_all()

    def label(self, text):
        return label(text, font="sans 14")

    def button(self, label, tooltip, relpath):
        def cb(_btn):
            cp = os.path.dirname(__file__)
            script = os.path.join(cp, relpath)
            if WIN32 and os.path.sep=="/":
                script = script.replace("/", "\\")
            if not os.path.exists(script):
                if os.path.exists(script+"c"):
                    script += "c"
                else:
                    log.warn("Warning: cannot find '%s'", os.path.basename(relpath))
                    return
            cmd = get_python_execfile_command()+[script]
            exec_command(cmd)
        return imagebutton(label, None,
                           tooltip, clicked_callback=cb,
                           icon_size=48)

    def quit(self, *args):
        log("quit%s", args)
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def show_about(self, *_args):
        from xpra.gtk_common.about import about
        about()


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready, set_default_icon
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    gtk_main_quit_on_fatal_exceptions_enable()
    with program_context("Xpra-Toolbox", "Xpra Toolbox"):
        enable_color()

        set_default_icon("toolbox.png")
        init()

        gui = ToolboxGUI()
        register_os_signals(gui.app_signal, "Xpra Toolbox")
        ready()
        gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":
    r = main()
    sys.exit(r)
