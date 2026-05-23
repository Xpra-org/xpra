# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from collections.abc import Callable

from xpra.exit_codes import ExitCode, ExitValue
from xpra.os_util import gi_import
from xpra.net.dispatch import PacketDispatcher
from xpra.net.common import Packet, PacketHandlerType
from xpra.util.glib import register_os_signals, register_SIGUSR_signals
from xpra.common import noerr
from xpra.util.signal_emitter import SignalEmitter
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "glib")


class GLibServer(SignalEmitter, PacketDispatcher):

    def __init__(self):
        SignalEmitter.__init__(self)
        PacketDispatcher.__init__(self)
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

    def print_run_info(self) -> None:
        log.info("GLibServer running")

    def signal_quit(self, _signum, _frame=None) -> None:
        self.do_quit()

    def run(self) -> ExitValue:
        self.print_run_info()
        self.install_signal_handlers(self.signal_quit)
        GLib.idle_add(self.server_is_ready)
        try:
            self.do_run()
        except KeyboardInterrupt:
            log.info("stopping on KeyboardInterrupt")
            self.cleanup()
            return ExitCode.OK
        log("run()")
        return 0

    def server_is_ready(self) -> None:
        self.emit("running")
        log.info("xpra is ready.")
        noerr(sys.stdout.flush)

    def call_packet_handler(self, main: bool, handler: PacketHandlerType, proto, packet: Packet) -> None:
        def call() -> None:
            handler(proto, packet)
        if main:
            GLib.idle_add(call)
        else:
            call()
