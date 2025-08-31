# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from queue import Queue
from typing import Any
from time import monotonic
from collections import deque
from collections.abc import Sequence

from xpra.util.env import envint
from xpra.util.objects import typedict, AtomicInteger
from xpra.scripts.config import InitExit
from xpra.client.base.adapter import RemoteServerAdapter
from xpra.codecs.constants import VideoSpec, TransientCodecException
from xpra.log import Logger

log = Logger("remote")

ENCODER_SERVER_TIMEOUT = envint("XPRA_ENCODER_SERVER_TIMEOUT", 5)
ENCODER_SERVER_SOCKET_TIMEOUT = envint("XPRA_ENCODER_SERVER_SOCKET_TIMEOUT", 1)
CONNECT_POLL_DELAY = envint("XPRA_CONNECT_POLL_DELAY", 10000)
RECONNECT_DELAY = envint("XPRA_RECONNECT_DELAY", 2000)


try:
    from xpra.client.subsystem.mmap import MmapClient
    baseclass = MmapClient
except ImportError:
    from xpra.client.base.stub import StubClientMixin
    baseclass = StubClientMixin


def get_version() -> Sequence[int]:
    return 0, 1


def get_type() -> str:
    return "remote"


def get_info() -> dict[str, Any]:
    return {"version": get_version()}


class RemoteCodecClient(RemoteServerAdapter):

    SYSTEM_SOCKET_PATH = "/run/xpra/encoder"
    PACKET_TYPES = RemoteServerAdapter.PACKET_TYPES + ["context-response", "context-data"]
    MODE = "encoder"

    def __init__(self, options: dict):
        super().__init__(options)
        log(f"RemoteCodecClient({options})")
        to = typedict(options)
        self.lz4 = to.boolget("lz4", False)
        self.specs: dict[str, dict[str, Sequence[VideoSpec]]] = {}

    def make_hello(self) -> dict[str, Any]:
        caps = super().make_hello()
        caps.update({
            "client_type": "encode",
            "windows": False,
            "keyboard": False,
            "wants": ("encodings", "video", ),
            "encoding": {"core": ("rgb32", "rgb24", )},
            "mouse": False,
            "network-state": False,  # tell older server that we don't have "ping"
        })
        return caps


class RemoteCodec:
    __slots__ = (
        "server", "codec_type",
        "generation", "encoding",
        "width", "height", "pixel_format", "last_frame_times",
        "ready", "closed", "responses",
        "__weakref__",
    )
    """
    Abstract base class for codecs that connects to a remote server and delegate to it
    """
    counter = AtomicInteger()

    def __init__(self, server: RemoteCodecClient, codec_type: str):
        self.server = server
        self.codec_type = codec_type
        self.generation = self.counter.increase()
        self.encoding = ""
        self.closed = False
        self.width = self.height = 0
        self.pixel_format = ""
        self.last_frame_times: deque[float] = deque(maxlen=200)
        self.ready = False
        self.responses = Queue(maxsize=1)

    def init_context(self, encoding: str, width: int, height: int, pixel_format: str, options: typedict) -> None:
        self.encoding = encoding
        self.width = width
        self.height = height
        self.pixel_format = pixel_format
        self.closed = False
        try:
            self.server.connect()
        except (OSError, InitExit) as e:
            log("failed to connect to remote encoder server %s", self.server)
            log(" %s", e)
            raise TransientCodecException(f"failed to connect: {e}") from None
        if not self.server.is_connected():
            raise TransientCodecException("not connected")

    def is_ready(self) -> bool:
        return self.ready

    def get_info(self) -> dict[str, Any]:
        info = get_info()
        if not self.pixel_format:
            return info
        info.update({
            "width": self.width,
            "height": self.height,
            "encoding": self.encoding,
            "pixel-format": self.pixel_format,
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
        if not self.pixel_format:
            return "remote-codec(uninitialized)"
        return f"remote-codec({self.pixel_format} - {self.width}x{self.height})"

    def is_closed(self) -> bool:
        return self.closed

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return f"remote-{self.codec_type}"

    def clean(self) -> None:
        self.closed = True
        self.width = 0
        self.height = 0
        self.encoding = ""
        self.pixel_format = ""
        self.last_frame_times = deque()
