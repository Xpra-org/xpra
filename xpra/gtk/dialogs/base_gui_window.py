# This file is part of Xpra.
# Copyright (C) 2018-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import subprocess
import gi
from collections.abc import Callable

from xpra.gtk.gtk_util import add_close_accel, add_window_accel
from xpra.gtk.widget import imagebutton, IgnoreWarningsContext
from xpra.gtk.pixbuf import get_icon_pixbuf
from xpra.exit_codes import exit_str
from xpra.common import NotificationID, noop
from xpra.platform.paths import get_xpra_command
from xpra.log import Logger

gi.require_version('Gdk', '3.0')  # @UndefinedVariable
gi.require_version('Gtk', '3.0')  # @UndefinedVariable
from gi.repository import GLib, Gtk, Gdk, Gio  # @UnresolvedImport

log = Logger("util")


def exec_command(cmd):
    env = os.environ.copy()
    env["XPRA_WAIT_FOR_INPUT"] = "0"
    proc = subprocess.Popen(cmd, env=env)
    log("exec_command(%s)=%s", cmd, proc)
    return proc


def button(tooltip:str, icon_name:str, callback:Callable):
    btn = Gtk.Button()
    icon = Gio.ThemedIcon(name=icon_name)
    image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
    btn.add(image)
    btn.set_tooltip_text(tooltip)

    def clicked(*_args):
        callback(btn)
    btn.connect("clicked", clicked)
    return btn


class BaseGUIWindow(Gtk.Window):

    def __init__(self,
                 title="Xpra",
                 icon_name="xpra.png",
                 wm_class=("xpra-gui", "Xpra-GUI"),
                 default_size=(640, 300),
                 header_bar=(True, True),
                 parent:Gtk.Window|None=None,
                 ):
        self.exit_code = 0
        super().__init__()
        if header_bar:
            self.add_headerbar(*header_bar)
        self.set_title(title)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.icon_name = icon_name
        icon = get_icon_pixbuf(icon_name)
        if icon:
            self.set_icon(icon)
        if parent:
            self.set_transient_for(parent)
            self.set_modal(True)
            self.do_dismiss = self.hide
        else:
            self.do_dismiss = self.quit
        self.connect("delete_event", self.dismiss)
        add_close_accel(self, self.dismiss)
        add_window_accel(self, 'F1', self.show_about)
        with IgnoreWarningsContext():
            self.set_wmclass(*wm_class)
        self.vbox = Gtk.VBox(homogeneous=False, spacing=10)
        self.add(self.vbox)
        self.populate()
        self.vbox.show_all()
        self.set_default_size(*default_size)
        self.connect("focus-in-event", self.focus_in)
        self.connect("focus-out-event", self.focus_out)

    def dismiss(self, *args):
        log(f"dismiss{args} calling {self.do_dismiss}")
        self.do_dismiss()


    def add_headerbar(self, about=True, toolbox=True):
        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "Xpra"
        if about:
            hb.add(button("About", "help-about", self.show_about))
        if toolbox:
            try:
                from xpra.gtk.dialogs.toolbox import ToolboxGUI
            except ImportError:
                pass
            else:
                def show(*_args):
                    w = None
                    def hide(*_args):
                        w.hide()
                    ToolboxGUI.quit = hide
                    w = ToolboxGUI()
                    w.show()
                hb.add(button("Toolbox", "applications-utilities", show))
        hb.show_all()
        self.set_titlebar(hb)

    def ib(self, title="", icon_name="browse.png", tooltip="", callback:Callable=noop, sensitive=True) -> None:
        label_font = "sans 16"
        icon = get_icon_pixbuf(icon_name)
        btn = imagebutton(
            title=title, icon=icon,
            tooltip=tooltip, clicked_callback=callback,
            icon_size=48, label_font=label_font,
        )
        self.add_widget(btn)

    def add_widget(self, widget):
        self.vbox.add(widget)

    def focus_in(self, window, event):
        log("focus_in(%s, %s)", window, event)

    def focus_out(self, window, event):
        log("focus_out(%s, %s)", window, event)
        self.reset_cursors()

    def app_signal(self, signum : int | signal.Signals):
        if self.exit_code is None:
            self.exit_code = 128 + int(signum)
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def hide(self, *args):
        log("hide%s", args)
        super().hide()

    def quit(self, *args):
        log("quit%s", args)
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()

    def show_about(self, *_args):
        from xpra.gtk.dialogs.about import about
        about(parent=self)

    def get_xpra_command(self, *args):
        return get_xpra_command()+list(args)

    def button_command(self, btn, *args):
        cmd = self.get_xpra_command(*args)
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.busy_cursor(btn)
            from xpra.util.child_reaper import getChildReaper
            getChildReaper().add_process(proc, "subcommand", cmd, ignore=True, forget=True, callback=self.command_ended)

    def command_ended(self, proc):
        self.reset_cursors()
        log(f"command_ended({proc})")
        if proc.returncode:

            self.may_notify(NotificationID.FAILURE,
                            "Subcommand Failed",
                            "The subprocess terminated abnormally\n\rand returned %s" % exit_str(proc.returncode)
                            )

    def busy_cursor(self, widget):
        from xpra.gtk.cursors import cursor_types
        watch = cursor_types.get("WATCH")
        if watch:
            display = Gdk.Display.get_default()
            cursor = Gdk.Cursor.new_for_display(display, watch)
            widget.get_window().set_cursor(cursor)
            GLib.timeout_add(5*1000, self.reset_cursors)

    def reset_cursors(self, *_args):
        for widget in self.vbox.get_children():
            widget.get_window().set_cursor(None)

    def exec_subcommand(self, subcommand, *args):
        log("exec_subcommand(%s, %s)", subcommand, args)
        cmd = get_xpra_command()
        cmd.append(subcommand)
        cmd += list(args)
        proc = exec_command(cmd)
        if proc.poll() is None:
            self.hide()
            def may_exit():
                if proc.poll() is None:
                    self.quit()
                else:
                    self.show()
            #don't ask me why,
            #but on macos we can get file descriptor errors
            #if we exit immediately after we spawn the attach command
            GLib.timeout_add(2000, may_exit)

    def may_notify(self, nid:NotificationID, summary:str, body:str):
        log.info(summary)
        log.info(body)
        from xpra.platform.gui import get_native_notifier_classes
        nc = get_native_notifier_classes()
        if not nc:
            return
        from xpra.util.types import make_instance
        notifier = make_instance(nc)
        if not notifier:
            return
        from xpra.platform.paths import get_icon_filename
        from xpra.notifications.common import parse_image_path
        icon_filename = get_icon_filename(self.icon_name)
        icon = parse_image_path(icon_filename)
        notifier.show_notify(0, None, nid,
                              "xpra GUI Window", 0, self.icon_name,
                              summary, body, {}, {}, 10, icon)
