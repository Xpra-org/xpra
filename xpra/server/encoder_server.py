# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.net.common import PacketType
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.gtk.signals import register_os_signals, register_SIGUSR_signals
from xpra.server.base import ServerBase, SERVER_BASES
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "encoding")


class EncoderServer(ServerBase):

    def __init__(self):
        log(f"EncoderServer.__init__() {SERVER_BASES=}")
        super().__init__()
        self.session_type = "encoder"
        self.loop = GLib.MainLoop()
        self.encode: Callable | None = None

    def init(self, opts) -> None:
        super().init(opts)
        from xpra.codecs.pillow.encoder import get_encodings, encode
        encodings = get_encodings()
        self.encode = encode
        if self.encoding not in ("auto", ) and self.encoding not in encodings:
            raise ValueError(f"unsupported encoding {self.encoding!r}")

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
        ss = self.get_server_source(proto)
        if not ss:
            return
        rgb_format = packet[1]
        raw_data = packet[2]
        width = packet[3]
        height = packet[4]
        rowstride = packet[5]
        options = packet[6]
        metadata = packet[7]
        depth = 32
        bpp = 4
        full_range = True
        encoding = "png" if ss.encoding in ("auto", "") else ss.encoding
        log("encode request from %s, encoding=%s from %s", ss, encoding, ss.encoding)
        # connection encoding options:
        eo = dict(ss.default_encoding_options)
        # the request can override:
        eo.update(options)
        log("using settings: %s", eo)
        from xpra.codecs.image import ImageWrapper, PlanarFormat
        image = ImageWrapper(0, 0, width, height, raw_data, rgb_format, depth, rowstride,
                             bpp, PlanarFormat.PACKED, True, None, full_range)
        coding, compressed, client_options, width, height, stride, bpp = self.encode(encoding, image, typedict(eo))
        packet = ["encode-response", coding, compressed.data, client_options, width, height, stride, bpp, metadata]
        ss.send_async(*packet)
