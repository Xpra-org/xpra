# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, GdkPixbuf

from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    add_window_accel, imagebutton,
    label,
    )
from xpra.platform.paths import get_icon_dir
from xpra.os_util import OSX
from xpra.log import Logger

log = Logger("client", "util")


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    proc = subprocess.Popen(cmd, env=env)
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
        icon = get_pixbuf("xpra")
        if icon:
            self.set_icon(icon)
        add_close_accel(self, self.quit)
        add_window_accel(self, 'F1', self.show_about)
        self.connect("delete_event", self.quit)

        self.vbox = Gtk.VBox(False, 10)
        self.add(self.vbox)

        self.vbox.add(label("Colors:", font="sans 16"))
        hbox = Gtk.HBox(False, 10)
        self.vbox.add(hbox)
        epath = "./example/"
        hbox.add(self.button("Squares", "Shows RGB+Grey squares in a window", epath+"colors_plain.py"))
        hbox.add(self.button("Animated Squares", "Shows RGB+Grey squares animated", epath+"colors.py"))
        hbox.add(self.button("Gradient", "Shows color gradients and visualize bit depth clipping", epath+"colors_gradient.py"))
        #hbox.add(self.button("GL Colors Gradient", "Shows gradients and visualize bit depth clipping", "encoding.png", None))

        self.vbox.add(label("Transparency:", font="sans 16"))
        hbox = Gtk.HBox(False, 10)
        self.vbox.add(hbox)
        hbox.add(self.button("Circle", "Shows a semi-opaque circle in a transparent window", epath+"transparent_window.py"))
        hbox.add(self.button("RGB Squares", "RGB+Black shaded squares in a transparent window", epath+"transparent_colors.py"))

        self.vbox.add(label("Misc:", font="sans 16"))
        hbox = Gtk.HBox(False, 10)
        self.vbox.add(hbox)
        hbox.add(self.button("Tray", "Show a system tray icon", epath+"tray.py"))
        hbox.add(self.button("Font Rendering", "Render characters with and without anti-aliasing", epath+"fontrendering.py"))
        hbox.add(self.button("Bell", "Test system bell", epath+"bell.py"))

        self.vbox.show_all()

    def button(self, label, tooltip, module):
        def cb(_btn):
            cp = os.path.dirname(__file__)
            script = os.path.join(cp, module)
            #TODO: win32 needs a python runner command
            exec_command(script)
        return imagebutton(label, None,
                           tooltip, clicked_callback=cb,
                           icon_size=48)

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()

    def app_signal(self, signum):
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.do_quit()

    def show_about(self, *_args):
        from xpra.gtk_common.about import about
        about()


def main():
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk_common.quit import gtk_main_quit_on_fatal_exceptions_enable
    gtk_main_quit_on_fatal_exceptions_enable()
    with program_context("Xpra-Toolbox", "Xpra Toolbox"):
        enable_color()
        init()
        gui = ToolboxGUI()
        register_os_signals(gui.app_signal)
        ready()
        if OSX:
            from xpra.platform.darwin.gui import wait_for_open_handlers
            wait_for_open_handlers(gui.show, gui.open_file, gui.open_url)
        else:
            gui.show()
        Gtk.main()
        log("do_main() gui.exit_code=%i", gui.exit_code)
        return 0


if __name__ == "__main__":
    r = main()
    sys.exit(r)
