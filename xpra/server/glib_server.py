# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.net.glib_handler import GLibPacketHandler
from xpra.util.glib import register_os_signals, register_SIGUSR_signals
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "glib")


class GLibServer(StubServerMixin, GLibPacketHandler):

    def __init__(self):
        StubServerMixin.__init__(self)
        GLibPacketHandler.__init__(self)
        self.main_loop = GLib.MainLoop()

    def __repr__(self):
        return "GLibServer"

    @staticmethod
    def install_signal_handlers(callback: Callable[[int], None]) -> None:
        sstr = "encoder server"
        register_os_signals(callback, sstr)
        register_SIGUSR_signals(sstr)

    def do_run(self) -> None:
        run: Callable = self.main_loop.run
        log("do_run() calling %s()", run)
        run()
        log("do_run() end of %()", run)

    def do_quit(self) -> None:
        log("do_quit: calling main_loop.quit()")
        self.main_loop.quit()
        # from now on, we can't rely on the main loop:
        from xpra.util.system import register_SIGUSR_signals
        register_SIGUSR_signals()
