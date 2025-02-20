# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from math import ceil
from time import monotonic
from collections.abc import Callable

from xpra.common import noop
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.net.common import PacketType
from xpra.net.compression import Compressed
from xpra.net.protocol.socket_handler import SocketProtocol
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.codecs.constants import COMPRESS_RATIO, COMPRESS_FMT_SUFFIX
from xpra.gtk.signals import register_os_signals, register_SIGUSR_signals
from xpra.server.base import ServerBase, SERVER_BASES
from xpra.codecs.video import getVideoHelper
from xpra.log import Logger

GLib = gi_import("GLib")

log = Logger("server", "encoder")
compresslog = Logger("compress")

# ensure we don't create loops!
codec_key = "xpra.codecs.remote"
assert codec_key not in sys.modules
sys.modules[codec_key] = None


COMPRESS_FMT = (
    "compress: %5.1fms for %4ix%-4i pixels at %4i,%-4i               using %9s" + COMPRESS_RATIO + COMPRESS_FMT_SUFFIX
)


class EncoderServer(ServerBase):

    def __init__(self):
        log(f"EncoderServer.__init__() {SERVER_BASES=}")
        super().__init__()
        self.session_type = "encoder"
        self.loop = GLib.MainLoop()
        self.encoders = {}

    def __repr__(self):
        return "EncoderServer"

    def init(self, opts) -> None:
        super().init(opts)
        from xpra.codecs.pillow.encoder import get_encodings
        encodings = get_encodings()
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
        # this function is only used by the `encode` client,
        # not the `remote` encoder
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
        try:
            from xpra.codecs.pillow.encoder import encode
            image = ImageWrapper(0, 0, width, height, rgb_data, rgb_format, depth, rowstride,
                                 bpp, PlanarFormat.PACKED, True, None, full_range)
            coding, compressed, client_options, width, height, stride, bpp = encode(encoding, image, typedict(eo))
        finally:
            free()
        packet = ["encode-response", coding, compressed.data, client_options, width, height, stride, bpp, metadata]
        ss.send_async(*packet)

    def _process_context_request(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, codec_type, encoding, width, height, src_format, options = packet[1:8]
        vh = getVideoHelper()
        specs = vh.get_encoder_specs(encoding).get(src_format, ())
        if not specs:
            ss.send("context-response", seq, False, "matching encoder not found", {})
            return
        # ensure we have a cuda context,
        # even if mmap is enabled!
        device_context = ss.allocate_cuda_device_context()
        log(f"request: {encoding}, cuda_device_context={device_context}")
        if device_context:
            options["cuda-device-context"] = device_context

        def find_spec():
            for espec in specs:
                if espec.codec_type != codec_type:
                    continue
                assert espec.encoding == encoding
                assert espec.input_colorspace == src_format
                return espec
            return specs[0]
        spec = find_spec()
        try:
            encoder = spec.codec_class()
            encoder.init_context(encoding, width, height, src_format, typedict(options))
            self.encoders[seq] = encoder
            log(f"new encoder: {encoder}")
            ss.send("context-response", seq, True, "", encoder.get_info())
        except RuntimeError as e:
            log("context request failed", exc_info=True)
            ss.send("context-response", seq, False, f"initialization error: {e}", {})

    def _process_context_compress(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, metadata, pixels, options = packet[1:5]
        encoder = self.encoders[seq]
        encoding = encoder.get_encoding()
        free_cb = []
        chunks = options.get("chunks", ())
        planes = metadata.get("planes", 0)
        log("compress request with %i planes, mmap chunks=%s", planes, chunks)
        start = monotonic()
        if not pixels and chunks:
            # get the pixels from the mmap chunks:
            if planes == PlanarFormat.PACKED:
                pixels, free = ss.mmap_read_area.mmap_read(*chunks)
                free_cb.append(free)
            else:
                pixels = []
                for plane in range(planes):
                    plane_pixels, free = ss.mmap_read_area.mmap_read(*chunks[plane])
                    free_cb.append(free)
                    pixels.append(plane_pixels)
        metadata["pixels"] = pixels
        try:
            image = ImageWrapper(**metadata)
            log(f"{encoder=} {image=}")
            device_context = ss.allocate_cuda_device_context()
            if device_context:
                options["cuda-device-context"] = device_context
            bdata, client_options = encoder.compress_image(image, typedict(options))
        finally:
            for free in free_cb:
                free()
        if bdata is None:
            raise RuntimeError("no data!")
        mmap_write_area = getattr(ss, "mmap_write_area", None)
        log(f"{len(bdata)} bytes, {client_options=}, {mmap_write_area=}")
        if mmap_write_area:
            client_options["chunks"] = mmap_write_area.write_data(bdata)
            data = b""
        else:
            data = Compressed(encoding, bdata)
        ss.send("context-data", seq, data, client_options)
        end = monotonic()
        csize = len(bdata)
        psize = image.get_bytesperpixel() * image.get_width() * image.get_height()
        x = image.get_x()
        y = image.get_y()
        outw = encoder.get_width()
        outh = encoder.get_height()
        compresslog(COMPRESS_FMT,
                    (end-start) * 1000, outw, outh, x, y, encoding,
                    100.0*csize/psize, ceil(psize/1024), ceil(csize/1024),
                    seq, client_options, options)
