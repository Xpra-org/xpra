# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from time import monotonic
from collections import deque
from collections.abc import Sequence

from xpra.codecs.image import ImageWrapper
from xpra.util.objects import typedict
from xpra.util.str_fn import memoryview_to_bytes
from xpra.log import Logger

log = Logger("encoder", "proxy")


def get_version() -> Sequence[int]:
    return 0, 2


def get_type() -> str:
    return "proxy"


def get_info() -> dict[str, Any]:
    return {"version": get_version()}


def get_encodings() -> Sequence[str]:
    return ("proxy",)


class Encoder:
    """
        This is a "fake" encoder which just forwards
        the raw pixels and the metadata that goes with it.
    """

    def init_context(self, encoding: str, width: int, height: int, src_format: str, options: typedict) -> None:
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.dst_formats = options.strtupleget("dst-formats")
        self.last_frame_times: deque[float] = deque(maxlen=200)
        self.frames = 0
        self.time = 0
        self.first_frame_timestamp = 0

    def is_ready(self) -> bool:
        return True

    def get_info(self) -> dict[str, Any]:
        info = get_info()
        if not self.src_format:
            return info
        info.update({
            "frames": self.frames,
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
            return "proxy_encoder(uninitialized)"
        return f"proxy_encoder({self.src_format} - {self.width}x{self.height})"

    def is_closed(self) -> bool:
        return not bool(self.src_format)

    def get_encoding(self) -> str:
        return self.encoding

    def get_width(self) -> int:
        return self.width

    def get_height(self) -> int:
        return self.height

    def get_type(self) -> str:
        return "proxy"

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
        self.frames = 0
        self.time = 0
        self.first_frame_timestamp = 0

    def compress_image(self, image: ImageWrapper, options: typedict) -> tuple[bytes, dict]:
        log("compress_image(%s, %s)", image, options)
        # pass the pixels as they are
        if image.get_planes() != ImageWrapper.PACKED:
            raise RuntimeError(f"invalid number of planes: {image.get_planes()}")
        pixels = image.get_pixels()
        if not pixels:
            raise RuntimeError(f"failed to get pixels from {image}")
        # info used by proxy encoder:
        client_options = {
            "proxy": True,
            "frame": self.frames,
            "pts": image.get_timestamp() - self.first_frame_timestamp,
            "timestamp": image.get_timestamp(),
            "rowstride": image.get_rowstride(),
            "depth": image.get_depth(),
            "rgb_format": image.get_pixel_format(),
            # pass-through encoder options:
            "options": options or {},
        }
        if self.frames == 0:
            self.first_frame_timestamp = image.get_timestamp()
            # must pass dst_formats so the proxy can instantiate the video encoder
            # with the correct CSC config:
            client_options["dst_formats"] = self.dst_formats
        log("compress_image(%s, %s) returning %s bytes and options=%s", image, options, len(pixels), client_options)
        self.last_frame_times.append(monotonic())
        self.frames += 1
        return memoryview_to_bytes(pixels[:]), client_options
