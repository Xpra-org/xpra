# This file is part of Xpra.
# Copyright (C) 2020-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# pylint: disable=wrong-import-position

import sys
import glob
import os.path
import subprocess
from collections.abc import Iterable, Sequence

from xpra.util.child_reaper import getChildReaper
from xpra.gtk.signals import register_os_signals
from xpra.gtk.window import add_close_accel
from xpra.gtk.widget import imagebutton, label
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.gtk.dialogs.util import hb_button
from xpra.platform.paths import get_python_execfile_command, get_python_exec_command
from xpra.os_util import WIN32, gi_import
from xpra.util.env import IgnoreWarningsContext
from xpra.log import Logger

Gtk = gi_import("Gtk")
Gio = gi_import("Gio")

log = Logger("client", "util")


def exec_command(cmd: Sequence[str]) -> subprocess.Popen:
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    creationflags = 0
    if WIN32:
        creationflags = subprocess.CREATE_NO_WINDOW  # @UndefinedVariable
    proc = subprocess.Popen(cmd, env=env, creationflags=creationflags)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


TITLE = "Xpra Toolbox"

EPATH = "xpra.gtk.examples."
BUTTON_GROUPS: dict[str, Iterable[tuple[str, str, str]]] = {
    "Colors": (
        ("Squares", "Shows RGB+Grey squares in a window", EPATH + "colors_plain"),
        ("Animated", "Shows RGB+Grey squares animated", EPATH + "colors"),
        ("Bit Depth", "Shows color gradients and visualize bit depth clipping", EPATH + "colors_gradient"),
    ),
    "Transparency and Rendering": (
        ("Circle", "Shows a semi-opaque circle in a transparent window", EPATH + "transparent_window"),
        ("RGB Squares", "RGB+Black shaded squares in a transparent window", EPATH + "transparent_colors"),
        ("OpenGL", "OpenGL window - transparent on some platforms", EPATH + "opengl"),
    ),
    "Widgets": (
        ("Text Entry", "Simple text entry widget", EPATH + "text_entry"),
        ("File Selector", "Open the file selector widget", EPATH + "file_chooser"),
        ("Header Bar", "Window with a custom header bar", EPATH + "header_bar"),
    ),
    "Events": (
        ("Grabs", "Test keyboard and pointer grabs", EPATH + "grabs"),
        ("Clicks", "Double and triple click events", EPATH + "clicks"),
        ("Focus", "Shows window focus events", EPATH + "window_focus"),
    ),
    "Windows": (
        ("States", "Toggle various window attributes", EPATH + "window_states"),
        ("Title", "Update the window title", EPATH + "window_title"),
        ("Opacity", "Change window opacity", EPATH + "window_opacity"),
        ("Transient", "Show transient windows", EPATH + "window_transient"),
        ("Override Redirect", "Shows an override redirect window", EPATH + "window_overrideredirect"),
    ),
    "Geometry": (
        ("Size constraints", "Specify window geometry size constraints", EPATH + "window_geometry_hints"),
        ("Move-Resize", "Initiate move resize from application", EPATH + "initiate_moveresize"),
    ),
    "Keyboard and Clipboard": (
        ("Keyboard", "Keyboard event viewer", "xpra.gtk.dialogs.view_keyboard"),
        ("Clipboard", "Clipboard event viewer", "xpra.gtk.dialogs.view_clipboard"),
    ),
    "Misc": (
        ("Tray", "Show a system tray icon", EPATH + "tray"),
        ("Font Rendering", "Render characters with and without anti-aliasing", EPATH + "fontrendering"),
        ("Bell", "Test system bell", EPATH + "bell"),
        ("Cursors", "Show named cursors", EPATH + "cursors"),
    ),
}


def get_cmd(modpath: str) -> list[str]:
    cp = os.path.dirname(__file__)
    script_path = os.path.join(cp, "../../../" + modpath.replace(".", "/"))
    if WIN32 and os.path.sep == "/":
        script_path = script_path.replace("/", "\\")
    script_path = os.path.abspath(script_path)
    script = script_path + ".py"
    cmd = []
    if os.path.exists(script):
        cmd = get_python_execfile_command() + [script]
    else:
        for compiled_ext in (".pyc", ".*.pyd", ".*.so"):
            script = script_path + compiled_ext
            matches = glob.glob(script)
            log(f"glob.glob({script})={matches}")
            if matches and os.path.exists(matches[0]):
                cmd = get_python_exec_command() + [f"from {modpath} import main;main()"]
                break
    if not cmd:
        log.warn(f"Warning: cannot find '{modpath}'")
    else:
        log(f"{modpath!r} : {cmd}")
    return cmd


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
        hb.add(hb_button("About", "help-about", self.show_about))
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

        def addhbox(blabel: str, buttons: Iterable[tuple[str, str, str]]) -> None:
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
    def button(label_str, tooltip, modpath, enabled=True) -> Gtk.Button:
        cmd = get_cmd(modpath)
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

    def quit(self, *args) -> None:
        log("quit%s", args)
        Gtk.main_quit()

    def app_signal(self, signum) -> None:
        self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def show_about(self, *_args) -> None:
        from xpra.gtk.dialogs.about import about
        about(parent=self)


def main(args) -> int:
    if len(args) == 1:
        # find a matching script or label:
        match = args[0].lower()
        for category, button_defs in BUTTON_GROUPS.items():
            for btn_label, tooltip, modpath in button_defs:
                if btn_label.lower() == match or modpath.split(".")[-1] == match:
                    cmd = get_cmd(modpath)
                    proc = exec_command(cmd)
                    return proc.wait()

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
