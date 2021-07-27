# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
import subprocess

from gi.repository import Gtk, Pango, GLib

from xpra.os_util import POSIX, OSX, which
from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.gtk_common.gtk_util import (
    add_close_accel,
    get_icon_pixbuf,
    imagebutton,
    )
from xpra.make_thread import start_thread
from xpra.log import Logger

log = Logger("client", "util")


def exec_command(cmd):
    env = os.environ.copy()
    proc = subprocess.Popen(cmd, env=env)
    return proc


def xal(widget, xalign=1):
    al = Gtk.Alignment(xalign=xalign, yalign=0.5, xscale=0, yscale=0)
    al.add(widget)
    return al

def sf(w, font="sans 14"):
    w.modify_font(Pango.FontDescription(font))
    return w

def l(label):
    widget = Gtk.Label(label)
    return sf(widget)


class DesktopGreeter(Gtk.Window):

    def __init__(self):
        self.exit_code = None
        Gtk.Window.__init__(self)
        self.set_border_width(20)
        self.set_title("Start Desktop Environment")
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_size_request(640, 300)
        icon = get_icon_pixbuf("xpra.png")
        if icon:
            self.set_icon(icon)
        self.connect("delete-event", self.quit)
        add_close_accel(self, self.quit)

        vbox = Gtk.VBox(False, 0)
        vbox.set_spacing(10)

        #self.entry_label = l("Command:")
        #vbox.add(self.entry_label)
        self.desktop_combo = sf(Gtk.ComboBoxText())
        vbox.add(self.desktop_combo)

        # Action buttons:
        hbox = Gtk.HBox(False, 20)
        vbox.pack_start(hbox, False, True, 20)
        def btn(label, tooltip, callback, default=False):
            ib = imagebutton(label, tooltip=tooltip, clicked_callback=callback, icon_size=32,
                            default=default, label_font=Pango.FontDescription("sans 16"))
            hbox.pack_start(ib)
            return ib
        self.cancel_btn = btn("Exit", "", self.quit)
        self.run_btn = btn("Start", "Start the desktop environment", self.run_command)

        vbox.show_all()
        self.add(vbox)
        start_thread(self.load_desktop_session, "load-desktop-sessions", daemon=True)

    def app_signal(self, signum):
        if self.exit_code is None:
            self.exit_code = 128 + signum
        log("app_signal(%s) exit_code=%i", signum, self.exit_code)
        self.quit()

    def quit(self, *args):
        log("quit%s", args)
        if self.exit_code is None:
            self.exit_code = 0
        self.do_quit()

    def do_quit(self):
        log("do_quit()")
        Gtk.main_quit()

    def run_command(self, *_args):
        name = self.desktop_combo.get_active_text()
        cmd = name
        if cmd in self.desktop_sessions:
            session = self.desktop_sessions.get(cmd)
            #ie:
            # session={
            #    'Type': '',
            #    'VersionString': '',
            #    'Name': 'Deepin',
            #    'GenericName': '',
            #    'NoDisplay': False,
            #    'Comment': 'Deepin Desktop Environment',
            #    'Icon': '',
            #    'Hidden': False,
            #    'OnlyShowIn': [],
            #    'NotShowIn': [],
            #    'Exec': '/usr/bin/startdde',
            #    'TryExec': '/usr/bin/startdde',
            #    'Path': '',
            #    'Terminal': False,
            #    'MimeTypes': [],
            #    'Categories': [],
            #    'StartupNotify': False,
            #    'StartupWMClass': '',
            #    'URL': '',
            #    'command': '/usr/bin/startdde',
            #    'IconData': b'<svg>...</svg>\n',
            #    'IconType': 'svg'
            #    }
            for k in ("command", "Exec", "TryExec"):
                cmd = session.get(k)
                if cmd:
                    break
        if cmd and not os.path.isabs(cmd):
            cmd = which(cmd)
        if not cmd:
            log.warn("no command found for '%s'", name)
            return
        argv = [cmd]
        self.destroy()
        os.execv(cmd, argv)

    def wait_for_subprocess(self, proc):
        proc.wait()
        log("return code: %s", proc.returncode)
        GLib.idle_add(self.show)

    def load_desktop_session(self):
        from xpra.server.menu_provider import get_menu_provider
        self.desktop_sessions = get_menu_provider().get_desktop_sessions()
        GLib.idle_add(self.populate_xsessions)

    def populate_xsessions(self):
        log("populate_xsessions()")
        self.desktop_combo.get_model().clear()
        if self.desktop_sessions:
            for name in sorted(self.desktop_sessions.keys()):
                self.desktop_combo.append_text(name)
        else:
            self.desktop_combo.append_text("xterm")
        self.desktop_combo.set_active(0)


def main(options=None): # pragma: no cover
    assert POSIX and not OSX
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    with program_context("xpra-start-gui", "Xpra Start GUI"):
        enable_color()
        init()
        gui = DesktopGreeter()
        register_os_signals(gui.app_signal)
        ready()
        gui.show()
        gui.present()
        Gtk.main()
        log("do_main() gui.exit_code=%s", gui.exit_code)
        return gui.exit_code


if __name__ == "__main__":  # pragma: no cover
    r = main()
    sys.exit(r)
