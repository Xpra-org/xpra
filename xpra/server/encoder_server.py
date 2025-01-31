# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.net.common import PacketType
from xpra.net.protocol.socket_handler import SocketProtocol

from xpra.os_util import gi_import
from xpra.gtk.signals import register_os_signals, register_SIGUSR_signals
from xpra.server.base import ServerBase
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")


class EncoderServer(ServerBase):

    def __init__(self):
        log("EncoderServer.__init__()")
        super().__init__()
        self.session_type = "encoder"
        self.loop = GLib.MainLoop()

    def install_signal_handlers(self, callback: Callable[[int], None]) -> None:
        sstr = self.get_server_mode() + " server"
        register_os_signals(callback, sstr)
        register_SIGUSR_signals(sstr)

    def do_run(self) -> None:
        log("do_run() calling %s", self.loop.run)
        self.loop.run()
        log("do_run() end of %()", self.loop.run)

    def do_quit(self) -> None:
        log("do_quit: calling loop.quit()")
        self.loop.quit()
        # from now on, we can't rely on the main loop:
        from xpra.util.system import register_SIGUSR_signals
        register_SIGUSR_signals()

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("encode")

    def _process_encode(self, proto: SocketProtocol, packet: PacketType) -> None:
        packet = ["encoded"] + packet[1:]
        proto.send_now(packet)
