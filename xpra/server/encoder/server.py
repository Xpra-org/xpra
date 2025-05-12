# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import os.path
from math import ceil
from typing import Any
from time import monotonic
from collections.abc import Callable, Sequence

from xpra.common import noop, ConnectionMessage
from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
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


SAVE_TO_FILE = os.environ.get("XPRA_SAVE_TO_FILE")
assert (not SAVE_TO_FILE) or SAVE_TO_FILE in ("jpeg", "png", "webp")

COMPRESS_FMT = (
    "compress: %5.1fms for %4ix%-4i pixels at %4i,%-4i               using %9s" + COMPRESS_RATIO + COMPRESS_FMT_SUFFIX
)


def add_device_context(ss, options: dict):
    device_context = ss.allocate_cuda_device_context()
    log(f"add_device_context: cuda_device_context={device_context}")
    if device_context:
        options["cuda-device-context"] = device_context


def _make_video_encoder(encoding: str, src_format: str, codec_type=""):
    specs = getVideoHelper().get_encoder_specs(encoding).get(src_format, ())
    if not specs:
        return None

    def find_spec():
        for espec in specs:
            if codec_type and espec.codec_type != codec_type:
                continue
            assert espec.encoding == encoding
            assert espec.input_colorspace == src_format
            return espec
        return specs[0]

    spec = find_spec()
    return spec.codec_class()


def csc_image(image: ImageWrapper, format_options: Sequence[str]) -> ImageWrapper | None:
    pixel_format = image.get_pixel_format()
    width = image.get_width()
    height = image.get_height()
    for fmt in format_options:
        for csc_spec in getVideoHelper().get_csc_specs(pixel_format).get(fmt, ()):
            log(f"csc {pixel_format!r} -> {csc_spec.codec_type!r} via {csc_spec!r}")
            converter = csc_spec.codec_class()
            converter.init_context(width, height, pixel_format, width, height, fmt, typedict())
            result = converter.convert_image(image)
            converter.clean()
            log(f" -> {result}")
            return result
    return None


class EncoderServer(ServerBase):

    def __init__(self):
        log(f"EncoderServer.__init__() {SERVER_BASES=}")
        super().__init__()
        self.session_type = "encoder"
        self.main_loop = GLib.MainLoop()
        self.encoders: dict[str, dict[int, Any]] = {}

    def __repr__(self):
        return "EncoderServer"

    def init(self, opts) -> None:
        super().init(opts)
        from xpra.codecs.pillow.encoder import get_encodings
        encodings = get_encodings()
        if self.encoding not in ("auto", ) and self.encoding not in encodings:
            raise ValueError(f"unsupported encoding {self.encoding!r}")
        # default to True rather than None (aka "auto"):
        self.sharing = self.sharing is not False

    def install_signal_handlers(self, callback: Callable[[int], None]) -> None:
        sstr = self.get_server_mode() + " server"
        register_os_signals(callback, sstr)
        register_SIGUSR_signals(sstr)

    def do_run(self) -> None:
        log("do_run() calling %s", self.main_loop.run)
        self.main_loop.run()
        log("do_run() end of %()", self.main_loop.run)

    def do_quit(self) -> None:
        log("do_quit: calling main_loop.quit()")
        self.main_loop.quit()
        # from now on, we can't rely on the main loop:
        from xpra.util.system import register_SIGUSR_signals
        register_SIGUSR_signals()

    def cleanup_source(self, source) -> None:
        encoders = self.encoders.pop(source.uuid, {})
        if encoders:
            for seq, encoder in encoders.items():
                try:
                    encoder.clean()
                except RuntimeError:
                    log.error(f"Error cleaning encoder {encoder} for sequence {seq} of connection {source}")
        super().cleanup_source(source)

    def init_packet_handlers(self) -> None:
        super().init_packet_handlers()
        self.add_packets("encode", "context-request", "context-compress", "context-close")

    def parse_hello(self, ss, c: typedict, send_ui: bool) -> None:
        super().parse_hello(ss, c, send_ui)
        from xpra.server.source.encodings import EncodingsMixin
        if not isinstance(ss, EncodingsMixin):
            raise ValueError("client did not enable encoding")

    def add_new_client(self, ss, c: typedict, send_ui: bool, share_count: int) -> None:
        super().add_new_client(ss, c, send_ui, share_count)
        ss.protocol.large_packets.append("encode-response")

    def _process_encode(self, proto: SocketProtocol, packet: PacketType) -> None:
        # this function is only used by the `encode` client,
        # not the `remote` encoder
        ss = self.get_server_source(proto)
        if not ss:
            return
        input_coding, pixel_format, raw_data, width, height, rowstride, options, metadata = packet[1:9]
        depth = 32
        bpp = 4
        full_range = True
        encoding = "png" if ss.encoding in ("auto", "") else ss.encoding
        log("encode request from %s, %s to %s (from %s)", ss, input_coding, encoding, ss.encoding)
        # connection encoding options:
        eo = dict(ss.default_encoding_options)
        # the request can override:
        eo.update(options)
        log("using settings: %s", eo)
        free = noop
        rgb_data = raw_data
        if input_coding == "mmap":
            if not ss.mmap_supported or not ss.mmap_read_area:
                raise RuntimeError("mmap packet but mmap read is not available")
            chunks = options.pop("chunks", ())
            rgb_data, free = ss.mmap_read_area.mmap_read(*chunks)
        if options.get("lz4") > 0:
            from xpra.net.lz4.lz4 import decompress
            rgb_data = decompress(rgb_data, max_size=64*1024*1024)
            free()
            free = noop

        try:
            image = ImageWrapper(0, 0, width, height, rgb_data, pixel_format, depth, rowstride,
                                 bpp, PlanarFormat.PACKED, True, None, full_range)
            if SAVE_TO_FILE:
                from xpra.codecs.debug import save_imagewrapper
                now = int(monotonic()*1000)
                filename = f"{now}.{SAVE_TO_FILE}"
                save_imagewrapper(image, filename)
                log.info(f"saved {image}, pixels={len(rgb_data)} {type(rgb_data)} to {filename!r}")
            from xpra.codecs.pillow.encoder import encode, get_encodings
            if encoding in get_encodings():
                # simple path: use pillow
                coding, compressed, client_options, width, height, stride, bpp = encode(encoding, image, typedict(eo))
                bdata = compressed.data
            else:
                # try a video encoder:
                encoder = _make_video_encoder(encoding, pixel_format)
                if not encoder:
                    msg = f"no video encoders found for {encoding!r} and {pixel_format!r}"
                    log(msg)
                    especs = getVideoHelper().get_encoder_specs(encoding)
                    input_cs_options = ()
                    if especs:
                        input_cs_options = tuple(especs.keys())
                        image = csc_image(image, input_cs_options)
                        if image:
                            pixel_format = image.get_pixel_format()
                            encoder = _make_video_encoder(encoding, pixel_format)
                    if not encoder:
                        log(f" supported pixel formats for {encoding!r}: %s", csv(input_cs_options))
                        raise ValueError(msg)
                add_device_context(ss, options)
                encoder.init_context(encoding, width, height, pixel_format, typedict(options))
                bdata, client_options = encoder.compress_image(image, typedict(options))
                bpp = 24
                stride = 0
                coding = encoding
        except (ValueError, RuntimeError) as e:
            log("encode failed", exc_info=True)
            self.disconnect_client(proto, ConnectionMessage.SERVER_ERROR, f"failed to encode: {e}")
            return
        finally:
            free()
        packet = ["encode-response", coding, bdata, client_options, width, height, stride, bpp, metadata]
        ss.send_async(*packet)

    def _process_context_close(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, message = packet[1:3]
        encoder = self.encoders.get(ss.uuid, {}).pop(seq, None)
        if not encoder:
            log(f"closing: encoder not found for uuid {ss.uuid!r} and sequence {seq}")
            return
        log(f"context-close: {encoder!r}, {message=}")
        try:
            encoder.clean()
        except RuntimeError:
            log.error(f"Error cleaning encoder {encoder} for sequence {seq} of connection {ss}")

    def _process_context_request(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, codec_type, encoding, width, height, src_format, options = packet[1:8]
        try:
            encoder = _make_video_encoder(encoding, src_format, codec_type)
            add_device_context(ss, options)
            encoder.init_context(encoding, width, height, src_format, typedict(options))
            self.encoders.setdefault(ss.uuid, {})[seq] = encoder
            log(f"new encoder: {encoder}")
            ss.send("context-response", seq, True, "", encoder.get_info())
        except RuntimeError as e:
            log("context request failed", exc_info=True)
            ss.send("context-response", seq, False, f"initialization error: {e}", {})

    def _process_context_compress(self, proto: SocketProtocol, packet: PacketType) -> None:
        ss = self.get_server_source(proto)
        if not ss:
            return
        seq, metadata, pixels, options, send_opts = packet[1:6]
        encoder = self.encoders.get(ss.uuid, {}).get(seq)
        if not encoder:
            log.error(f"Error encoder not found for uuid {ss.uuid!r} and sequence {seq}")
            ss.send("context-data", seq, b"", {"error": "context not found"}, {})
            return
        encoding = encoder.get_encoding()
        free_cb = []

        def free_all() -> None:
            for free_fn in free_cb:
                free_fn()
            free_cb[:] = []

        chunks = send_opts.pop("chunks", ())
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

        if send_opts.get("lz4", 0) > 0:
            from xpra.net.lz4.lz4 import decompress
            if planes == PlanarFormat.PACKED:
                pixels = decompress(pixels)
            else:
                pixels = [decompress(plane) for plane in pixels]
            free_all()

        metadata["pixels"] = pixels
        try:
            image = ImageWrapper(**metadata)
            log(f"{encoder=} {image=}")
            add_device_context(ss, options)
            bdata, client_options = encoder.compress_image(image, typedict(options))
        finally:
            free_all()

        delayed = client_options.get("delayed", 0)
        if bdata is None and not delayed:
            log.warn(f"Warning: no data from encoder {encoder}")
            log.warn(" options:%s", client_options)
            ss.send("context-data", seq, b"", {"error": "no data from encoder"}, {})
            return
        reply_opts = {}
        data = Compressed(encoding, bdata or b"")
        if len(data) >= 4096:
            mmap_write_area = getattr(ss, "mmap_write_area", None)
            log(f"{len(bdata)} bytes, {client_options=}, {mmap_write_area=}")
            if mmap_write_area:
                reply_opts["chunks"] = mmap_write_area.write_data(bdata)
                data = b""
        ss.send("context-data", seq, data, client_options, reply_opts)
        end = monotonic()
        csize = len(bdata or b"")
        psize = image.get_bytesperpixel() * image.get_width() * image.get_height()
        x = image.get_x()
        y = image.get_y()
        outw = encoder.get_width()
        outh = encoder.get_height()
        compresslog(COMPRESS_FMT,
                    (end-start) * 1000, outw, outh, x, y, encoding,
                    100.0*csize/psize, ceil(psize/1024), ceil(csize/1024),
                    seq, client_options, options)
