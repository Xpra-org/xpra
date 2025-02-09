# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import uuid
from typing import Any
from time import monotonic
from collections import deque
from collections.abc import Sequence
from threading import Event

from xpra import __version__
from xpra.util.env import envint
from xpra.net.common import PacketElement
from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("encoder")

ENCODER_SERVER_URI = os.environ.get("XPRA_ENCODER_SERVER_URI", "tcp://127.0.0.1:20000/")
ENCODER_SERVER_SOCKET_TIMEOUT = envint("XPRA_ENCODER_SERVER_TIMEOUT", 1)


class EncoderClient:

    def __init__(self, uri=""):
        self.uri = uri
        self.encodings: Sequence[str] = ()
        self.protocol = None
        self._ordinary_packets = []
        self.event = Event()

    def connect(self):
        from xpra.scripts.main import error_handler, parse_display_name, connect_to
        from xpra.scripts.config import make_defaults_struct
        opts = make_defaults_struct()
        desc = parse_display_name(error_handler, opts, self.uri)
        if "timeout" not in desc:
            desc["timeout"] = ENCODER_SERVER_SOCKET_TIMEOUT
        log(f"server desc={desc!r}")
        conn = connect_to(desc, opts)
        self.protocol = self.make_protocol(conn)
        self.send_hello()

    def send_hello(self):
        caps = {
            "version": __version__,
            "client_type": "encode",
            "session-id": uuid.uuid4().hex,
            "windows": False,
            "keyboard": False,
            "mouse": False,
            "network-state": False,  # tell older server that we don't have "ping"
        }
        from xpra.net.packet_encoding import get_packet_encoding_caps
        caps.update(get_packet_encoding_caps(0))
        from xpra.net.compression import get_compression_caps
        caps.update(get_compression_caps(0))
        self.send("hello", caps)
        self.event.clear()
        self.protocol.start()
        self.event.wait(1)

    def send(self, packet_type: str, *parts: PacketElement) -> None:
        packet = (packet_type, *parts)
        # direct mode:
        # self.protocol._add_packet_to_queue(packet)
        # while self.protocol._write_queue.qsize():
        #    self.protocol._write()
        self._ordinary_packets.append(packet)
        self.protocol.source_has_more()

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
        # self.add_packet_handler("setting-change", noop)
        # if conn.timeout > 0:
        #    GLib.timeout_add((conn.timeout + EXTRA_TIMEOUT) * 1000, self.verify_connected)
        return protocol

    def _process_packet(self, proto, packet):
        log.warn(f"received {packet!r}")

    def _next_packet(self):
        return self._ordinary_packets.pop(0), True, bool(self._ordinary_packets)

    def disconnect(self):
        p = self.protocol
        if p:
            self.protocol = None
            p.close()

    def get_encodings(self):
        return self.encodings


def get_version() -> Sequence[int]:
    return 0, 1


def get_type() -> str:
    return "remote"


def get_info() -> dict[str, Any]:
    return {"version": get_version()}


server = EncoderClient(ENCODER_SERVER_URI)


def get_encodings() -> Sequence[str]:
    return server.get_encodings()


def init_module() -> None:
    uri = ENCODER_SERVER_URI
    log(f"remote.init_module() attempting to connect to {uri!r}")
    server.connect()


def cleanup_module() -> None:
    log("remote.cleanup_module()")
    server.disconnect()


class Encoder:
    """
    This encoder connects to an encoder server and delegates to it
    """

    def init_context(self, encoding: str, width: int, height: int, src_format: str, options: typedict) -> None:
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.dst_formats = options.strtupleget("dst-formats")
        self.last_frame_times: deque[float] = deque(maxlen=200)
        self.ready = False

    def is_ready(self) -> bool:
        return self.ready

    def get_info(self) -> dict[str, Any]:
        info = get_info()
        if self.src_format is None:
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
        if self.src_format is None:
            return "remote_encoder(uninitialized)"
        return f"remote_encoder({self.src_format} - {self.width}x{self.height})"

    def is_closed(self) -> bool:
        return self.src_format is None

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
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.encoding = ""
        self.src_format = ""
        self.dst_formats = []
        self.last_frame_times = deque()

    def compress_image(self, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        pass
