# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import uuid
from queue import Queue, Empty
from typing import Any
from time import monotonic
from collections import deque
from collections.abc import Sequence
from weakref import WeakValueDictionary
from threading import Event

from xpra import __version__
from xpra.util.env import envint
from xpra.util.objects import typedict, AtomicInteger
from xpra.scripts.config import InitExit
from xpra.net.common import PacketElement, PacketType
from xpra.codecs.constants import VideoSpec
from xpra.codecs.image import ImageWrapper, PlanarFormat
from xpra.log import Logger

log = Logger("encoder", "remote")

ENCODER_SERVER_TIMEOUT = envint("XPRA_ENCODER_SERVER_TIMEOUT", 5)
ENCODER_SERVER_URI = os.environ.get("XPRA_ENCODER_SERVER_URI", "tcp://127.0.0.1:20000/")
ENCODER_SERVER_SOCKET_TIMEOUT = envint("XPRA_ENCODER_SERVER_TIMEOUT", 1)

try:
    from xpra.client.mixins.mmap import MmapClient
    baseclass = MmapClient
except ImportError:
    baseclass = object


class EncoderClient(baseclass):

    def __init__(self, uri=""):
        self.uri = uri
        self.encodings: Sequence[str] = ()
        self.specs: dict[str, dict[str, Sequence[VideoSpec]]] = {}
        self.protocol = None
        self._ordinary_packets = []
        self.event = Event()
        self.encoders = WeakValueDictionary()
        if baseclass != object:
            from xpra.scripts.config import XpraConfig
            opts = XpraConfig()
            opts.mmap = "both"
            opts.mmap_group = ""
            MmapClient.init(self, opts)

    def connect(self, retry=False) -> None:
        if self.protocol:
            log("already connected")
            return
        from xpra.scripts.main import error_handler, parse_display_name, connect_to
        from xpra.scripts.config import make_defaults_struct
        opts = make_defaults_struct()
        desc = parse_display_name(error_handler, opts, self.uri)
        if "timeout" not in desc:
            desc["timeout"] = ENCODER_SERVER_SOCKET_TIMEOUT
        if "retry" not in desc:
            desc["retry"] = retry
        log(f"server desc={desc!r}")
        conn = connect_to(desc, opts)
        if baseclass != object:
            MmapClient.setup_connection(self, conn)
        self.protocol = self.make_protocol(conn)
        self.send_hello()

    def make_protocol(self, conn):
        from xpra.net.packet_encoding import init_all
        init_all()
        from xpra.net.compression import init_all
        init_all()
        from xpra.net.protocol.factory import get_client_protocol_class
        protocol_class = get_client_protocol_class(conn.socktype)
        protocol = protocol_class(conn, self._process_packet, self._next_packet)
        protocol.enable_default_encoder()
        protocol.enable_default_compressor()
        protocol._log_stats = False
        protocol.large_packets += ["encodings", "context-compress", "context-data"]
        # self.add_packet_handler("setting-change", noop)
        # if conn.timeout > 0:
        #    GLib.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        return protocol

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        packet = (packet_type, *parts)
        self._ordinary_packets.append(packet)
        self.protocol.source_has_more()

    def _process_packet(self, proto, packet: PacketType) -> None:
        packet_type = packet[0]
        if packet_type in (
                "hello", "encodings", "startup-complete",
                "setting-change",
                "connection-lost", "disconnect",
                "context-response", "context-data",
        ):
            fn = getattr(self, "_process_%s" % packet_type.replace("-", "_"))
            fn(packet)
        else:
            log.warn(f"Warning: received unexpected {packet_type!r} from encoder server connection {proto}")

    def send_hello(self) -> None:
        caps = {
            "version": __version__,
            "client_type": "encode",
            "uuid": uuid.uuid4().hex,
            "windows": False,
            "keyboard": False,
            "wants": ("encodings", "video", ),
            "encoding": {"core": ("rgb32", "rgb24", )},
            "mouse": False,
            "network-state": False,  # tell older server that we don't have "ping"
        }
        if baseclass != object:
            caps.update(MmapClient.get_caps(self))
        from xpra.net.packet_encoding import get_packet_encoding_caps
        caps.update(get_packet_encoding_caps(0))
        from xpra.net.compression import get_compression_caps
        caps.update(get_compression_caps(0))
        log(f"sending hello={caps!r}")
        self.send("hello", caps)
        self.event.clear()
        self.protocol.start()
        self.event.wait(ENCODER_SERVER_TIMEOUT)

    def _process_hello(self, packet: PacketType) -> None:
        caps = packet[1]
        log("got hello: %s", caps)
        if baseclass != object:
            MmapClient.parse_server_capabilities(self, typedict(caps))

    def _process_encodings(self, packet: PacketType) -> None:
        log(f"{packet!r}")
        self.specs = typedict(packet[1]).dictget("video") or {}
        self.encodings = tuple(self.specs.keys())
        log("got encodings=%s", self.encodings)
        log("from specs=%s", self.specs)

    def _process_disconnect(self, packet: PacketType) -> None:
        log("disconnected from server %s", self.protocol)
        self.encodings = ()
        self.protocol = None

    def _process_connection_lost(self, packet: PacketType) -> None:
        log("connection-lost for server %s", self.protocol)
        self.encodings = ()
        self.protocol = None

    def _process_startup_complete(self, packet: PacketType) -> None:
        log(f"{packet!r}")
        self.event.set()

    def _next_packet(self) -> tuple[Any, bool, bool]:
        return self._ordinary_packets.pop(0), True, bool(self._ordinary_packets)

    def disconnect(self) -> None:
        p = self.protocol
        if p:
            self.protocol = None
            p.close()

    def get_encodings(self) -> Sequence[str]:
        return self.encodings

    def request_context(self, encoder, encoding: str, width: int, height: int, src_format: str, options: dict):
        seq = encoder.sequence
        codec_type = encoder.codec_type
        self.encoders[seq] = encoder
        self.send("context-request", seq, codec_type, encoding, width, height, src_format, options)

    def _process_context_response(self, packet: PacketType):
        seq = packet[1]
        ok = packet[2]
        message = "" if len(packet) < 4 else packet[3]
        encoder = self.encoders.get(seq)
        log(f"context-response: {seq}={encoder}, {ok=}, {message=!r}")
        if not encoder:
            log.error(f"Error: encoder {seq} not found!")
            return
        if ok:
            encoder.ready = True
        else:
            encoder.closed = True

    def compress(self, encoder, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        log("compress%s", (encoder, image, options))
        metadata = {}
        for attr in ("x", "y", "width", "height", "pixel_format", "depth", "rowstride", "bytesperpixel", "planes", "full_range"):
            metadata[attr] = getattr(image, f"get_{attr}")()
        pixels = image.get_pixels()
        mmap_write_area = getattr(self, "mmap_write_area", None)
        if mmap_write_area:
            nplanes = image.get_planes()
            if nplanes == PlanarFormat.PACKED:
                mmap_data = mmap_write_area.write_data(pixels)
                log("sending image via mmap: %s", mmap_data)
            else:
                mmap_data = []
                for plane in range(nplanes):
                    plane_data = mmap_write_area.write_data(pixels[plane])
                    log("sending plane %i via mmap: %s", plane, plane_data)
                    mmap_data.append(plane_data)
            options["chunks"] = tuple(mmap_data)
            pixels = b""
        self.send("context-compress", encoder.sequence, metadata, pixels, options)

    def _process_context_data(self, packet: PacketType):
        seq, bdata, client_options = packet[1:4]
        encoder = self.encoders.get(seq)
        if not encoder:
            log.error(f"Error: encoder {seq} not found!")
            return
        chunks = client_options.pop("chunks", ())
        if not bdata and chunks:
            mmap_read_area = getattr(self, "mmap_read_area", None)
            mmap_data, free = mmap_read_area.mmap_read(*chunks)
            bdata = bytes(mmap_data)
            free()
        log("server replied with %i bytes", len(bdata))
        encoder.compressed_data(bdata, client_options)


def get_version() -> Sequence[int]:
    return 0, 1


def get_type() -> str:
    return "remote"


def get_info() -> dict[str, Any]:
    return {"version": get_version()}


server = EncoderClient(ENCODER_SERVER_URI)
encodings: Sequence[str] = ()


def get_encodings() -> Sequence[str]:
    return encodings


def init_module() -> None:
    uri = ENCODER_SERVER_URI
    log(f"remote.init_module() attempting to connect to {uri!r}")
    global encodings
    try:
        server.connect()
    except (InitExit, OSError, RuntimeError):
        log("failed to connect to server, no encodings available", exc_info=True)
        encodings = ()
    else:
        encodings = server.get_encodings()


def cleanup_module() -> None:
    log("remote.cleanup_module()")
    server.disconnect()


def make_spec(espec: dict) -> VideoSpec:
    codec_type = espec.pop("codec_type")

    class RemoteEncoder(Encoder):
        def __init__(self):
            super().__init__(codec_type)

    spec = VideoSpec(codec_class=RemoteEncoder, codec_type=f"remote-{codec_type}")
    for k, v in espec.items():
        if not hasattr(spec, k):
            log.warn(f"Warning: unknown video spec attribute {k!r}")
            continue
        setattr(spec, k, v)
    return spec


def get_specs() -> Sequence[VideoSpec]:
    # the `server.specs` are dictionaries,
    # which we need to convert to real `VideoSpec` objects:
    specs: Sequence[VideoSpec] = []
    for encoding, csc_specs in server.specs.items():
        for csc, especs in csc_specs.items():
            for espec in especs:
                log(f"remote: {encoding} + {csc}: {espec}")
                specs.append(make_spec(espec))
    log(f"remote.get_specs()={specs}")
    return tuple(specs)


sequence = AtomicInteger()


class Encoder:
    __slots__ = (
        "codec_type", "sequence", "encoding",
        "width", "height", "src_format", "dst_formats", "last_frame_times",
        "ready", "closed", "responses",
        "__weakref__",
    )
    """
    This encoder connects to an encoder server and delegates to it
    """
    def __init__(self, codec_type: str):
        self.codec_type = codec_type

    def init_context(self, encoding: str, width: int, height: int, src_format: str, options: typedict) -> None:
        self.sequence = sequence.increase()
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.dst_formats = options.strtupleget("dst-formats")
        self.last_frame_times: deque[float] = deque(maxlen=200)
        self.ready = False
        self.closed = False
        server.connect()
        server.request_context(self, encoding, width, height, src_format, dict(options))
        self.responses = Queue(maxsize=1)

    def is_ready(self) -> bool:
        return self.ready

    def get_info(self) -> dict[str, Any]:
        info = get_info()
        if not self.src_format:
            return info
        info.update({
            "width": self.width,
            "height": self.height,
            "encoding": self.encoding,
            "src_format": self.src_format,
            "dst_formats": self.dst_formats,
        })
        # calculate fps:
        now = monotonic()
        last_time = now
        cut_off = now - 10.0
        f = 0
        for v in tuple(self.last_frame_times):
            if v > cut_off:
                f += 1
                last_time = min(last_time, v)
        if f > 0 and last_time < now:
            info["fps"] = int(0.5 + f / (now - last_time))
        return info

    def __repr__(self):
        if not self.src_format:
            return "remote_encoder(uninitialized)"
        return f"remote_encoder({self.src_format} - {self.width}x{self.height})"

    def is_closed(self) -> bool:
        return self.closed

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "remote"

    def get_src_format(self) -> str:
        return self.src_format

    def clean(self) -> None:
        self.closed = True
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.src_format = ""
        self.dst_formats = ()
        self.last_frame_times = deque()

    def compress_image(self, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        server.compress(self, image, options)
        try:
            return self.responses.get(timeout=1)
        except Empty:
            log.warn("Warning: remote encoder timeout waiting for server response")
            return b"", {}

    def compressed_data(self, bdata, client_options: dict) -> None:
        log(f"received compressed data: {len(bdata)}, {client_options=}")
        self.responses.put((bdata, client_options))
