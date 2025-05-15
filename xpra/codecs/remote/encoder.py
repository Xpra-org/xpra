# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from queue import Empty
from collections.abc import Sequence
from weakref import WeakValueDictionary

from xpra.util.str_fn import Ellipsizer, print_nested_dict
from xpra.util.objects import typedict
from xpra.scripts.config import InitExit
from xpra.net.common import Packet
from xpra.codecs.constants import VideoSpec, CodecStateException
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.codecs.remote.common import get_type, get_version, get_info, RemoteCodecClient, RemoteCodec
from xpra.log import Logger

log = Logger("encoder", "remote")

ENCODINGS = tuple(x for x in os.environ.get("XPRA_REMOTE_ENCODINGS", "h264,vp8,vp9").split(",") if x)


def safe_dict(opts: dict | typedict) -> dict:
    # a simple dictionary suitable for sending via rencodeplus
    # (removes floats and other illegal values - floats are not strictly illegal, but we don't use them)
    return dict((k, v) for k, v in opts.items() if isinstance(k, str) and isinstance(v, (int, str, bool)))


class EncoderClient(RemoteCodecClient):

    def __init__(self, options: dict):
        super().__init__(options)
        self.specs = {}
        self.encoders = WeakValueDictionary()
        self.encodings: Sequence[str] = ()

    def __repr__(self):
        return "EncoderClient(%s)" % self.uri

    def server_connection_cleanup(self) -> None:
        super().server_connection_cleanup()
        self.specs = {}
        self.encodings = ()

    def _process_encodings(self, packet: Packet) -> None:
        log(f"{Ellipsizer(packet)!r}")
        specs = typedict(packet.get_dict(1)).dictget("video") or {}
        self.specs = dict((k, v) for k, v in specs.items() if k in ENCODINGS)
        log("received specs=%s", Ellipsizer(specs))
        log("filtered specs:")
        print_nested_dict(self.specs, print_fn=log)
        encodings = tuple(self.specs.keys())
        self.encodings = tuple(set(encodings) & set(ENCODINGS))
        log("received encodings=%s", encodings)
        log("filtered encodings=%s", self.encodings)

    def request_close(self, seq: int, message="") -> None:
        if self.is_connected():
            self.send("context-close", seq, message)

    def request_context(self, encoder, encoding: str, width: int, height: int, src_format: str, options: dict) -> None:
        seq = encoder.generation
        codec_type = encoder.codec_type
        self.encoders[seq] = encoder
        sopts = safe_dict(options)
        self.send("context-request", seq, codec_type, encoding, width, height, src_format, sopts)

    def _process_context_response(self, packet: Packet) -> None:
        seq = packet.get_u64(1)
        ok = packet.get_bool(2)
        message = "" if len(packet) < 4 else packet.get_str(3)
        info = {} if len(packet) < 5 else packet.get_dict(4)
        encoder = self.encoders.get(seq)
        log(f"context-response: {seq}={encoder}, {ok=}, {message=!r}, {info=}")
        if not encoder:
            log(f"context response ignored, encoder {seq} not found!")
            return
        if ok:
            encoder.ready = True
        else:
            encoder.closed = True

    def compress(self, seq, image: ImageWrapper, options: typedict) -> None:
        log("compress%s", (seq, image, options))
        metadata = {}
        for attr in ("x", "y", "width", "height", "depth", "bytesperpixel", "planes"):
            metadata[attr] = int(getattr(image, f"get_{attr}")())
        for attr in ("rowstride", "pixel_format", "full_range"):
            metadata[attr] = getattr(image, f"get_{attr}")()
        pixels = image.get_pixels()
        nplanes = image.get_planes()
        send_opts = {}
        if self.lz4:
            send_opts["lz4"] = True
            from xpra.net.lz4.lz4 import compress
            if nplanes == PlanarFormat.PACKED:
                pixels = compress(pixels)
            else:
                pixels = [compress(plane) for plane in pixels]

        mmap_write_area = getattr(self, "mmap_write_area", None)
        if mmap_write_area:
            if nplanes == PlanarFormat.PACKED:
                mmap_data = mmap_write_area.write_data(pixels)
                log("sending image via mmap: %s", mmap_data)
            else:
                mmap_data = []
                for plane in range(nplanes):
                    plane_data = mmap_write_area.write_data(pixels[plane])
                    log("sending plane %i via mmap: %s", plane, plane_data)
                    mmap_data.append(plane_data)
            send_opts["chunks"] = tuple(mmap_data)
            pixels = b""
        self.send("context-compress", seq, metadata, pixels, safe_dict(options), send_opts)

    def _process_context_data(self, packet: Packet) -> None:
        seq = packet.get_u64(1)
        bdata = packet.get_buffer(2)
        client_options = packet.get_dict(3)
        reply_opts = packet.get_dict(4)
        encoder = self.encoders.get(seq)
        if not encoder:
            log.error(f"Error: data unused, encoder {seq} not found!")
            return
        chunks = reply_opts.pop("chunks", ())
        if not bdata and chunks:
            mmap_read_area = getattr(self, "mmap_read_area", None)
            mmap_data, free = mmap_read_area.mmap_read(*chunks)
            bdata = bytes(mmap_data)
            free()
        log("server replied with %i bytes, client-options=%s", len(bdata), client_options)
        encoder.compressed_data(bdata, client_options)


servers: list[EncoderClient] = []


def add_server(options: dict) -> None:
    try:
        server = EncoderClient(options)
        server.connect()
        log("%s: %s, %s", get_type(), get_version(), get_info())
        servers.append(server)
    except (InitExit, OSError, RuntimeError):
        log("failed to connect to server, no encodings available", exc_info=True)


def init_module(options: dict) -> None:
    log(f"encoder.init_module({options})")
    # single server syntax uses "uri=protocol://host:port/.."
    # or one can use multiple servers with "uris=protocol://host1/?attr=value&,protocol://host2/"
    global servers
    uris = options.get("uris", "")
    if uris:
        for uri in uris.split(";"):
            uri_override = options.copy()
            uri_override["uri"] = uri
            add_server(uri_override)
    # single uri:
    uri = options.get("uri", "")
    if uri:
        add_server(options)


def cleanup_module() -> None:
    log("remote.cleanup_module()")
    global servers
    for server in servers:
        server.cancel_schedule_connect()
        server.disconnect()
    servers[:] = []


def make_spec(server: EncoderClient, espec: dict) -> VideoSpec:
    codec_type = espec["codec_type"]

    class RemoteEncoder(Encoder):
        def __init__(self):
            super().__init__(server, codec_type)

    spec = VideoSpec(codec_class=RemoteEncoder, codec_type=f"remote-{codec_type}")
    for k, v in espec.items():
        if k == "codec_type":
            continue
        if not hasattr(spec, k):
            log.warn(f"Warning: unknown video spec attribute {k!r}")
            continue
        setattr(spec, k, v)

    def get_runtime_factor() -> float:
        return float(server.is_connected())

    spec.get_runtime_factor = get_runtime_factor
    return spec


def get_encodings() -> Sequence[str]:
    encodings: list[str] = []
    for server in servers:
        encodings += server.encodings
    return tuple(encodings)


def get_specs() -> Sequence[VideoSpec]:
    # the `server.specs` are dictionaries,
    # which we need to convert to real `VideoSpec` objects:
    global servers
    specs: Sequence[VideoSpec] = []
    for server in servers:
        for encoding, csc_specs in server.specs.items():
            for csc, especs in csc_specs.items():
                for espec in especs:
                    log(f"remote: {encoding} + {csc}: {espec}")
                    specs.append(make_spec(server, espec))
    log(f"remote.get_specs()={specs}")
    return tuple(specs)


class Encoder(RemoteCodec):

    def init_context(self, encoding: str, width: int, height: int, src_format: str, options: typedict) -> None:
        super().init_context(encoding, width, height, src_format, options)
        self.server.request_context(self, encoding, width, height, src_format, dict(options))

    def __repr__(self):
        if not self.pixel_format:
            return "remote.encoder(uninitialized)"
        return f"remote.encoder({self.pixel_format} - {self.width}x{self.height})"

    def get_src_format(self) -> str:
        return self.pixel_format

    def clean(self) -> None:
        super().clean()
        self.responses.put((b"", {}))
        self.server.request_close(self.generation, "encoder closed")

    def compress_image(self, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        if not self.server.is_connected():
            raise CodecStateException("not connected to encoder server")
        self.server.compress(self.generation, image, options)
        try:
            return self.responses.get(timeout=1)
        except Empty:
            log.warn("Warning: remote encoder timeout waiting for server response")
            log.warn(f" for {self.encoding!r} compression of {image}")
            self.closed = not self.server.is_connected()
            return b"", {}

    def compressed_data(self, bdata, client_options: dict) -> None:
        log(f"received {self.encoding!r} compressed data: {len(bdata)} bytes, {client_options=}")
        self.responses.put((bdata, client_options))
