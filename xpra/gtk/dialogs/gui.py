# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

from xpra.os_util import OSX, WIN32, gi_import
from xpra.gtk.dialogs.base_gui_window import BaseGUIWindow
from xpra.log import Logger

Gtk = gi_import("Gtk")

log = Logger("util")


def has_client() -> bool:
    try:
        from xpra import client
        return bool(client)
    except ImportError:
        return False


def has_mdns() -> bool:
    try:
        from xpra.net.mdns import util
        return bool(util)
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


def has_configure() -> bool:
    try:
        from xpra.gtk import configure
        return bool(configure)
    except ImportError:
        return False


class GUI(BaseGUIWindow):

    def __init__(self, argv=()):
        self.argv = argv
        self.widgets = []
        super().__init__(header_bar=(True, True, True))

    def populate(self) -> None:
        def browse_tooltip() -> str:
            if not has_client():
                return "the client is not installed"
            if not has_mdns():
                return "the mdns module is not installed"
            return "Browse and connect to local and mDNS sessions"
        self.ib("Browse", "browse.png", browse_tooltip(), self.browse, sensitive=has_client() and has_mdns())

        def connect_tooltip() -> str:
            if not has_client():
                return "the client is not installed"
            return "Connect to an existing session\nover the network"
        self.ib("Connect", "connect.png", connect_tooltip(), self.show_launcher, sensitive=has_client())

        def shadow_tooltip() -> str:
            if not has_shadow():
                return "the shadow server feature is not installed"
            return "\n".join((
                "Start a shadow server,",
                "making this desktop accessible to others",
                "(authentication required)",
            ))
        self.ib("Shadow", "server-connected.png", shadow_tooltip(), self.shadow, sensitive=has_shadow())

        self.ib("Configure", "ticked.png", "", self.configure, sensitive=has_configure())

        def start_tooltip() -> str:
            if not has_client():
                return "the client is not installed"
            return "Start a new %sxpra session" % ("remote " if not has_server() else "")
        self.ib("Start", "windows.png", start_tooltip(), self.start, sensitive=has_client())

        grid = Gtk.Grid()
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)
        for i, widget in enumerate(self.widgets):
            grid.attach(widget, i % 2, i // 2, 1, 1)
        self.vbox.add(grid)

    def add_widget(self, widget) -> None:
        self.widgets.append(widget)

    def get_xpra_command(self, *args) -> list[str]:
        argv = list(self.argv[1:])
        try:
            if argv.index("gui") >= 0:
                argv.pop(argv.index("gui"))
        except ValueError:
            pass
        return super().get_xpra_command(*args) + argv

    def configure(self, button) -> None:
        self.button_command(button, "configure")

    def shadow(self, button) -> None:
        cmd_args = ["shadow", "--bind-tcp=0.0.0.0:14500,auth=sys,ssl-cert=auto"] if (WIN32 or OSX) else ["shadow"]
        self.button_command(button, *cmd_args)

    def browse(self, btn) -> None:
        self.button_command(btn, "sessions")

    def show_launcher(self, btn) -> None:
        self.button_command(btn, "launcher")

    def start(self, btn) -> None:
        self.button_command(btn, "start-gui")

    def open_file(self, filename: str) -> None:
        log("open_file(%s)", filename)
        self.exec_subcommand("launcher", filename)

    def open_url(self, url: str) -> None:
        log("open_url(%s)", url)
        self.exec_subcommand("attach", url)


def main(argv):  # pragma: no cover
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
