# This file is part of Xpra.
# Copyright (C) 2018-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gi

from xpra.os_util import OSX, WIN32
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.log import Logger

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

log = Logger("client", "util")


def has_client() -> bool:
    try:
        from xpra import client
        return bool(client)
    except ImportError:
        return False


def has_server() -> bool:
    try:
        from xpra.server import util
        return bool(util)
    except ImportError:
        return False


def has_shadow() -> bool:
    try:
        from xpra.server import shadow
        return bool(shadow)
    except ImportError:
        return False


class GUI(BaseGUIWindow):

    def __init__(self, argv=()):
        self.argv = argv
        self.widgets = []
        super().__init__()

    def populate(self):
        if has_client():
            self.ib("Browse", "browse.png","Browse and connect to local and mDNS sessions", self.browse)
            self.ib("Connect", "connect.png","Connect to an existing session\nover the network", self.show_launcher)
        if has_server():
            if has_shadow():
                tooltip = "\n".join((
                    "Start a shadow server,",
                    "making this desktop accessible to others",
                    "(authentication required)",
                ))
            else:
                tooltip = "This build of Xpra does not support starting shadow sessions"
            self.ib("Shadow", "server-connected.png", tooltip, self.shadow, sensitive=has_shadow)
            tooltip = "Start a new %sxpra session" % (" remote" if (WIN32 or OSX) else "")
            self.ib("Start", "windows.png", tooltip, self.start)
        table = Gtk.Table(n_rows=2, n_columns=2, homogeneous=True)
        for i, widget in enumerate(self.widgets):
            table.attach(widget, i%2, i%2+1, i//2, i//2+1, xpadding=10, ypadding=10)
        self.vbox.add(table)

    def add_widget(self, widget):
        self.widgets.append(widget)

    def get_xpra_command(self, *args):
        argv = list(self.argv[1:])
        if argv.index("gui")>=0:
            argv.pop(argv.index("gui"))
        return super().get_xpra_command(*args)+argv

    def shadow(self, button):
        cmd_args = ["shadow", "--bind-tcp=0.0.0.0:14500,auth=sys,ssl-cert=auto"] if (WIN32 or OSX) else ["shadow"]
        self.button_command(button, *cmd_args)

    def browse(self, btn):
        self.button_command(btn, "sessions")

    def show_launcher(self, btn):
        self.button_command(btn, "launcher")

    def start(self, btn):
        self.button_command(btn, "start-gui")

    def open_file(self, filename):
        log("open_file(%s)", filename)
        self.exec_subcommand("launcher", filename)

    def open_url(self, url):
        log("open_url(%s)", url)
        self.exec_subcommand("attach", url)


def main(argv): # pragma: no cover
    # pylint: disable=import-outside-toplevel
    from xpra.platform import program_context
    from xpra.log import enable_color
    from xpra.platform.gui import init, ready
    from xpra.gtk.signals import register_os_signals
    with program_context("xpra-gui", "Xpra GUI"):
        enable_color()
        init()
        gui = GUI(argv=argv)
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


if __name__ == "__main__":  # pragma: no cover
    r = main(sys.argv)
    sys.exit(r)
