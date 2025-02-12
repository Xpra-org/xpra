# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Callable

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.net.common import PacketType
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.codecs.image import ImageWrapper
from xpra.gtk.signals import register_os_signals, register_SIGUSR_signals
from xpra.server.base import ServerBase, SERVER_BASES
from xpra.codecs.video import getVideoHelper
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
        self.encoders = {}

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
        self.add_packets("encode", "context-request", "context-compress", )

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        super().add_new_client(ss, c, send_ui, share_count)
        ss.protocol.large_packets.append("encode-response")

    def _process_encode(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        input_coding, rgb_format, raw_data, width, height, rowstride, options, metadata = packet[1:9]
        depth = 32
        bpp = 4
        full_range = True
        encoding = "png" if ss.encoding in ("auto", "") else ss.encoding
        log("encode request from %s, %s to %s from %s", ss, input_coding, encoding, ss.encoding)
        # connection encoding options:
        eo = dict(ss.default_encoding_options)
        # the request can override:
        eo.update(options)
        log("using settings: %s", eo)
        from xpra.codecs.image import ImageWrapper, PlanarFormat
        if input_coding == "mmap":
            if not ss.mmap_supported or not ss.mmap_read_area:
                raise RuntimeError("mmap packet but mmap read is not available")
            chunks = options["chunks"]
            rgb_data, free = ss.mmap_read_area.mmap_read(*chunks)
        else:
            if options.get("lz4") > 0:
                from xpra.net.lz4.lz4 import decompress
                rgb_data = decompress(raw_data, max_size=64*1024*1024)
            else:
                rgb_data = raw_data
            free = noop
        image = ImageWrapper(0, 0, width, height, rgb_data, rgb_format, depth, rowstride,
                             bpp, PlanarFormat.PACKED, True, None, full_range)
        coding, compressed, client_options, width, height, stride, bpp = self.encode(encoding, image, typedict(eo))
        free()
        packet = ["encode-response", coding, compressed.data, client_options, width, height, stride, bpp, metadata]
        ss.send_async(*packet)

    def _process_context_request(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, encoding, width, height, src_format, options = packet[1:7]
        vh = getVideoHelper()
        specs = vh.get_encoder_specs(encoding).get(src_format, ())
        if not specs:
            ss.send("context-response", seq, False)
            return
        # we should be able to specify which one
        # and verify dimensions
        spec = specs[0]
        encoder = spec.codec_class()
        encoder.init_context(encoding, width, height, src_format, typedict(options))
        self.encoders[seq] = encoder
        log(f"new encoder: {encoder}")
        ss.send("context-response", seq, True)

    def _process_context_compress(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, metadata, pixels, options = packet[1:5]
        encoder = self.encoders[seq]
        metadata["pixels"] = pixels
        image = ImageWrapper(**metadata)
        log(f"{encoder=} {image=}")
        bdata, client_options = encoder.compress_image(image, typedict(options))
        if bdata is None:
            raise RuntimeError("no data!")
        log(f"{len(bdata)} bytes, {client_options=}")
        ss.send("context-data", seq, bdata, client_options)
