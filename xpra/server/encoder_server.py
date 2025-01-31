# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Callable

from xpra.net.common import PacketType
from xpra.net.protocol.socket_handler import SocketProtocol

from xpra.os_util import gi_import
from xpra.server import features
from xpra.gtk.signals import register_os_signals, register_SIGUSR_signals
from xpra.server.mixins.encoding import EncodingServer
from xpra.server.core import ServerCore
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server")


def get_encoder_server_base_classes() -> tuple[type, ...]:
    classes: list[type] = [ServerCore, EncodingServer]
    if features.dbus:
        from xpra.server.mixins.dbus import DbusServer
        classes.append(DbusServer)
    if features.http:
        from xpra.server.mixins.http import HttpServer
        classes.append(HttpServer)
    return tuple(classes)


SERVER_BASES = get_encoder_server_base_classes()
EncoderServerBaseClass = type('EncoderServerBaseClass', SERVER_BASES, {})


class EncoderServer(EncoderServerBaseClass):

    def __init__(self):
        log("EncoderServer.__init__()")
        for bc in SERVER_BASES:
            bc.__init__(self)
        self.session_type = "encoder"
        self.loop = GLib.MainLoop()

    def init(self, opts) -> None:
        opts.start_new_commands = False
        for bc in SERVER_BASES:
            bc.init(self, opts)

    def setup(self) -> None:
        for c in SERVER_BASES:
            c.setup(self)

    def threaded_init(self) -> None:
        for bc in SERVER_BASES:
            bc.threaded_setup(self)

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

    def get_info(self, proto) -> dict[str, Any]:
        info = ServerCore.get_info(self, proto)
        info.update(EncodingServer.get_info(self, proto))
        return info

    def cleanup(self) -> None:
        for bc in SERVER_BASES:
            bc.cleanup(self)

    def make_hello(self, source) -> dict[str, Any]:
        capabilities = super().make_hello(source)
        if "features" in source.wants:
            capabilities.update(EncoderServer.get_server_features(source))
        return capabilities

    def init_packet_handlers(self) -> None:
        ServerCore.init_packet_handlers(self)
        EncodingServer.init_packet_handlers(self)
        self.add_packets("encode")

    def _process_encode(self, proto: SocketProtocol, packet: PacketType) -> None:
        packet = ["encoded"] + packet[1:]
        proto.send_now(packet)
