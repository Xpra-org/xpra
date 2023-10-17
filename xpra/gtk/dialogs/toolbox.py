# This file is part of Xpra.
# Copyright (C) 2020-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import sys
import glob
import os.path
import subprocess
import gi
gi.require_version("Gtk", "3.0")  # @UndefinedVariable
gi.require_version("Gdk", "3.0")  # @UndefinedVariable
from gi.repository import Gtk, Gio  # @UnresolvedImport

from xpra.util.child_reaper import getChildReaper
from xpra.gtk.signals import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import imagebutton, label
from xpra.gtk.util import IgnoreWarningsContext
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.platform.paths import get_python_execfile_command, get_python_exec_command
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
        with IgnoreWarningsContext():
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

        epath = "xpra.gtk.examples."

        def addhbox(blabel, buttons):
            self.vbox.add(self.label(blabel))
            hbox = Gtk.HBox(homogeneous=False, spacing=10)
            self.vbox.add(hbox)
            for button in buttons:
                if button:
                    hbox.add(self.button(*button))

        #some things don't work on wayland:
        wox11 = WIN32 or OSX or (os.environ.get("GDK_BACKEND", "")=="x11" or is_X11())

        addhbox("Colors:", (
            ("Squares", "Shows RGB+Grey squares in a window", epath+"colors_plain"),
            ("Animated", "Shows RGB+Grey squares animated", epath+"colors"),
            ("Bit Depth", "Shows color gradients and visualize bit depth clipping", epath+"colors_gradient"),
            ))
        addhbox("Transparency and Rendering", (
            ("Circle", "Shows a semi-opaque circle in a transparent window", epath+"transparent_window"),
            ("RGB Squares", "RGB+Black shaded squares in a transparent window", epath+"transparent_colors"),
            ("OpenGL", "OpenGL window - transparent on some platforms", epath+"opengl", wox11),
            ))
        addhbox("Widgets:", (
            ("Text Entry", "Simple text entry widget", epath+"text_entry"),
            ("File Selector", "Open the file selector widget", epath+"file_chooser"),
            ("Header Bar", "Window with a custom header bar", epath+"header_bar"),
            ))
        addhbox("Events:", (
            ("Grabs", "Test keyboard and pointer grabs", epath+"grabs"),
            ("Clicks", "Double and triple click events", epath+"clicks"),
            ("Focus", "Shows window focus events", epath+"window_focus"),
            ))
        addhbox("Windows:", (
            ("States", "Toggle various window attributes", epath+"window_states"),
            ("Title", "Update the window title", epath+"window_title"),
            ("Opacity", "Change window opacity", epath+"window_opacity"),
            ("Transient", "Show transient windows", epath+"window_transient"),
            ("Override Redirect", "Shows an override redirect window", epath+"window_overrideredirect"),
            ))
        addhbox("Geometry:", (
            ("Size constraints", "Specify window geometry size constraints", epath+"window_geometry_hints"),
            ("Move-Resize", "Initiate move resize from application", epath+"initiate_moveresize", wox11),
            ))
        addhbox("Keyboard and Clipboard:", (
            ("Keyboard", "Keyboard event viewer", "xpra.gtk.dialogs.view_keyboard"),
            ("Clipboard", "Clipboard event viewer", "xpra.gtk.dialogs.view_clipboard"),
            ))
        addhbox("Misc:", (
                ("Tray", "Show a system tray icon", epath+"tray"),
                ("Font Rendering", "Render characters with and without anti-aliasing", epath+"fontrendering"),
                ("Bell", "Test system bell", epath+"bell"),
                ("Cursors", "Show named cursors", epath+"cursors"),
                ))
        self.vbox.show_all()

    @staticmethod
    def label(text):
        return label(text, font="sans 14")

    @staticmethod
    def button(label_str, tooltip, modpath, enabled=True):
        cp = os.path.dirname(__file__)
        script_path = os.path.join(cp, "../../../"+modpath.replace(".", "/"))
        if WIN32 and os.path.sep == "/":
            script_path = script_path.replace("/", "\\")
        script_path = os.path.abspath(script_path)
        script = script_path+".py"
        cmd = []
        if os.path.exists(script):
            cmd = get_python_execfile_command()+[script]
        else:
            for compiled_ext in (".pyc", ".*.pyd", ".*.so"):
                script = script_path + compiled_ext
                matches = glob.glob(script)
                log(f"glob.glob({script})={matches}")
                if matches and os.path.exists(matches[0]):
                    cmd = get_python_exec_command()+[f"from {modpath} import main;main()"]
                    break
        if not cmd:
            enabled = False
            log.warn(f"Warning: cannot find '{modpath}'")
        else:
            log(f"{label_str} : {cmd}")
        def cb(_btn):
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

    def show_about(self, *_args):
        from xpra.gtk.dialogs.about import about
        about(parent=self)


def main():
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
    r = main()
    sys.exit(r)
