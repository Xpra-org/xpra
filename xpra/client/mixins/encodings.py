# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Sequence

from xpra.codecs.constants import preforder, STREAM_ENCODINGS
from xpra.codecs.loader import load_codec, codec_versions, has_codec, get_codec, unload_codecs
from xpra.codecs.video import getVideoHelper
from xpra.scripts.config import parse_bool_or_int
from xpra.common import FULL_INFO, VIDEO_MAX_SIZE, noop
from xpra.net.common import PacketType
from xpra.net import compression
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import envint, envbool
from xpra.client.base.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("client", "encoding")

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)
SCROLL_ENCODING = envbool("XPRA_SCROLL_ENCODING", False)

# we assume that any server will support at least those:
DEFAULT_ENCODINGS = os.environ.get("XPRA_DEFAULT_ENCODINGS", "rgb32,rgb24,jpeg,png").split(",")


def get_core_encodings() -> Sequence[str]:
    """
        This method returns the actual encodings supported.
        ie: ["rgb24", "vp8", "webp", "png", "png/L", "png/P", "jpeg", "h264", "vpx"]
        It is often overridden in the actual client class implementations,
        where extra encodings can be added (generally just 'rgb32' for transparency),
        or removed if the toolkit implementation class is more limited.
    """
    # we always support rgb:
    core_encodings = ["rgb24", "rgb32"]
    for codec in ("dec_pillow", "dec_webp", "dec_jpeg", "dec_nvjpeg", "dec_avif"):
        if has_codec(codec):
            c = get_codec(codec)
            encs = c.get_encodings()
            log("%s.get_encodings()=%s", codec, encs)
            for e in encs:
                if e not in core_encodings:
                    core_encodings.append(e)
    if SCROLL_ENCODING:
        core_encodings.append("scroll")
    # we enable all the video decoders we know about,
    # but what will actually get used by the server will still depend
    # on the csc modes supported by the client
    video_decodings = getVideoHelper().get_decodings()
    log("video_decodings=%s", video_decodings)
    for encoding in video_decodings:
        if encoding not in core_encodings:
            core_encodings.append(encoding)
    # remove duplicates and use preferred encoding order:
    return preforder(core_encodings)


def get_batch_caps() -> dict[str, Any]:
    # batch options:
    caps = {}
    for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
        evalue = os.environ.get(f"XPRA_BATCH_{bprop.upper()}")
        if evalue:
            try:
                caps[f"batch.{bprop}"] = int(evalue)
            except ValueError:
                log.error("Error: invalid environment value for %s: %s", bprop, evalue)
    log("get_batch_caps()=%s", caps)
    return caps


class Encodings(StubClientMixin):
    """
    Mixin for adding encodings to a client
    """
    PREFIX = "encoding"

    def __init__(self):
        self.allowed_encodings = []
        self.encoding = ""
        self.quality = -1
        self.min_quality = 0
        self.speed = 0
        self.min_speed = -1
        self.video_scaling = None
        self.video_max_size = VIDEO_MAX_SIZE

        self.server_encodings: Sequence[str] = ()
        self.server_core_encodings: Sequence[str] = ()
        self.server_encodings_with_speed: Sequence[str] = ()
        self.server_encodings_with_quality: Sequence[str] = ()
        self.server_encodings_with_lossless_mode: Sequence[str] = ()

        # what we told the server about our encoding defaults:
        self.encoding_defaults = {}

    def init(self, opts) -> None:
        self.allowed_encodings = opts.encodings
        self.encoding = opts.encoding
        if opts.video_scaling.lower() in ("auto", "on"):
            self.video_scaling = None
        else:
            self.video_scaling = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.quality = opts.quality
        self.min_quality = opts.min_quality
        self.speed = opts.speed
        self.min_speed = opts.min_speed
        load_codec("dec_pillow")
        ae = self.allowed_encodings
        if "png" in ae:
            # try to load the fast png decoder:
            load_codec("dec_spng")
        if "jpeg" in ae:
            # try to load the fast jpeg decoders:
            load_codec("dec_jpeg")
            load_codec("dec_nvjpeg")
            load_codec("nvdec")
        if "webp" in ae:
            # try to load the fast webp decoder:
            load_codec("dec_webp")
        if "avif" in ae:
            load_codec("dec_avif")
        vh = getVideoHelper()
        vh.set_modules(video_decoders=opts.video_decoders, csc_modules=opts.csc_modules)
        vh.init()

    def cleanup(self) -> None:
        with log.trap_error("Error during video helper cleanup"):
            getVideoHelper().cleanup()
        unload_codecs()

    def init_authenticated_packet_handlers(self) -> None:
        self.add_packets(f"{Encodings.PREFIX}-set")
        self.add_legacy_alias("encodings", f"{Encodings.PREFIX}-set")

    def _process_encoding_set(self, packet: PacketType) -> None:
        caps = typedict(packet[1])
        Encodings._parse_server_capabilities(self, caps)
        # fire setting change event for the system-tray:
        ssc = getattr(self, "server_setting_changed", noop)
        ssc("encoding", caps)

    def get_info(self) -> dict[str, Any]:
        return {
            "encodings": {
                "core": self.get_core_encodings(),
                "window-icon": self.get_window_icon_encodings(),
                "cursor": self.get_cursor_encodings(),
                "quality": self.quality,
                "min-quality": self.min_quality,
                "speed": self.speed,
                "min-speed": self.min_speed,
                "encoding": self.encoding or "auto",
                "video-scaling": self.video_scaling if self.video_scaling is not None else "auto",
            },
            "server-encodings": self.server_core_encodings,
        }

    def get_caps(self) -> dict[str, Any]:
        caps = {
            "encodings": {
                "": self.get_encodings(),
                "all": self.get_encodings(),
                "core": self.get_core_encodings(),
                "window-icon": self.get_window_icon_encodings(),
                "cursor": self.get_cursor_encodings(),
                "packet": True,
            },
            "batch": get_batch_caps(),
            "encoding": self.get_encodings_caps(),
        }
        return caps

    def parse_server_capabilities(self, c: typedict) -> bool:
        self._parse_server_capabilities(c)
        return True

    def _parse_server_capabilities(self, c) -> None:
        self.server_encodings = c.strtupleget("encodings", DEFAULT_ENCODINGS)
        self.server_core_encodings = c.strtupleget("encodings.core", self.server_encodings)
        # old servers only supported x264:
        self.server_encodings_with_speed = c.strtupleget("encodings.with_speed", ("h264",))
        self.server_encodings_with_quality = c.strtupleget("encodings.with_quality", ("jpeg", "webp", "h264"))
        self.server_encodings_with_lossless_mode = c.strtupleget("encodings.with_lossless_mode", ())
        e = c.strget("encoding")
        if e and not c.boolget("encodings.delayed"):
            if self.encoding and e != self.encoding:
                if self.encoding not in self.server_core_encodings:
                    log.warn("server does not support %s encoding and has switched to %s", self.encoding, e)
                else:
                    log.info("server is using %s encoding instead of %s", e, self.encoding)
            self.encoding = e

    def get_encodings_caps(self) -> dict[str, Any]:
        video_b_frames: list[str] = []
        if B_FRAMES:
            video_b_frames.append("h264")  # only tested with dec_avcodec2
        caps: dict[str, Any] = {
            "video_b_frames": video_b_frames,
            "video_max_size": self.video_max_size,
            "max-soft-expired": MAX_SOFT_EXPIRED,
            "send-timestamps": SEND_TIMESTAMPS,
        }
        if self.video_scaling is not None:
            caps["scaling.control"] = self.video_scaling
        if self.encoding:
            caps[""] = self.encoding
            # since v6.3:
            caps["setting"] = self.encoding
        if FULL_INFO > 1:
            for k, v in codec_versions.items():
                caps[f"{k}.version"] = v
        if self.quality > 0:
            caps["quality"] = self.quality
        if self.min_quality > 0:
            caps["min-quality"] = self.min_quality
        if self.speed >= 0:
            caps["speed"] = self.speed
        if self.min_speed >= 0:
            caps["min-speed"] = self.min_speed

        # generic rgb compression flags:
        if "lz4" in compression.get_enabled_compressors():
            caps["rgb_lz4"] = True
        # these are the defaults - when we instantiate a window,
        # we can send different values as part of the map event
        # these are the RGB modes we want (the ones we are expected to be able to paint with):
        rgb_formats = ["RGB", "RGBX", "RGBA"]
        caps["rgb_formats"] = rgb_formats
        # figure out which CSC modes (usually YUV) can give us those RGB modes:
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*rgb_formats)
        if has_codec("dec_webp"):
            full_csc_modes["webp"] = ["BGRX", "BGRA", "RGBX", "RGBA"] if self.opengl_enabled else ["BGRX", "BGRA"]
        if has_codec("dec_jpeg") or has_codec("dec_pillow"):
            full_csc_modes["jpeg"] = ["BGRX", "BGRA", "YUV420P"]
        if has_codec("dec_jpeg"):
            full_csc_modes["jpega"] = ["BGRA", "RGBA"]
        log("supported full csc_modes=%s", full_csc_modes)
        caps["full_csc_modes"] = full_csc_modes

        if "h264" in self.get_core_encodings():
            # some profile options: "baseline", "main", "high", "high10", ...
            # set the default to "high10" for YUV420P
            # as the python client always supports all the profiles
            # whereas on the server side, the default is baseline to accommodate less capable clients.
            # YUV422P requires high422, and
            # YUV444P requires high444,
            # so we don't bother specifying anything for those two.
            h264_caps = {}
            for csc_name, default_profile in (
                    ("YUV420P", "high"),
                    ("YUV422P", ""),
                    ("YUV444P", ""),
            ):
                profile = os.environ.get(f"XPRA_H264_{csc_name}_PROFILE", default_profile)
                if profile:
                    h264_caps[f"{csc_name}.profile"] = profile
            h264_caps["fast-decode"] = envbool("XPRA_X264_FAST_DECODE", False)
            log("x264 encoding options: %s", h264_caps)
            caps["h264"] = h264_caps
        caps["batch"] = get_batch_caps()
        log("encoding capabilities: %s", caps)
        return caps

    def get_encodings(self) -> Sequence[str]:
        """
            Unlike get_core_encodings(), this method returns "rgb" for both "rgb24" and "rgb32".
            That's because although we may support both, the encoding chosen is plain "rgb",
            and the actual encoding used ("rgb24" or "rgb32") depends on the window's bit depth.
            ("rgb32" if there is an alpha channel, and if the client supports it)
        """
        cenc = [{"rgb32": "rgb", "rgb24": "rgb"}.get(x, x) for x in self.get_core_encodings()]
        if "grayscale" not in cenc and "png/L" in cenc:
            cenc.append("grayscale")
        if any(x in cenc for x in STREAM_ENCODINGS):
            cenc.append("stream")
        return preforder(cenc)

    def get_cursor_encodings(self) -> list[str]:
        e = ["raw", "default"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def get_window_icon_encodings(self) -> list[str]:
        e = ["BGRA", "default"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def get_core_encodings(self) -> list[str]:
        core = get_core_encodings()
        r = [x for x in core if x in self.allowed_encodings]
        log(f"get_core_encodings()={r} (core={core}, allowed={self.allowed_encodings})")
        return r

    def set_encoding(self, encoding: str) -> None:
        log("set_encoding(%s)", encoding)
        if encoding != "auto":
            encodings = self.get_encodings()
            if encoding not in encodings:
                raise ValueError(f"encoding {encoding} is not supported - only {csv(encodings)!r}")
            if encoding not in self.server_encodings:
                log.error(f"Error: encoding {encoding} is not supported by the server")
                log.error(" the only encodings allowed are:")
                log.error(" " + csv(self.server_encodings))
                return
        self.encoding = encoding
        self.send("encoding", self.encoding)

    def send_quality(self) -> None:
        q = self.quality
        log("send_quality() quality=%s", q)
        if q != -1 and (q < 0 or q > 100):
            raise ValueError(f"invalid quality: {q}")
        self.send("quality", q)

    def send_min_quality(self) -> None:
        q = self.min_quality
        log("send_min_quality() min-quality=%s", q)
        if q != -1 and (q < 0 or q > 100):
            raise ValueError(f"invalid min-quality: {q}")
        self.send("min-quality", q)

    def send_speed(self) -> None:
        s = self.speed
        log("send_speed() min-speed=%s", s)
        if s != -1 and (s < 0 or s > 100):
            raise ValueError(f"invalid speed: {s}")
        self.send("speed", s)

    def send_min_speed(self) -> None:
        s = self.min_speed
        log("send_min_speed() min-speed=%s", s)
        if s != -1 and (s < 0 or s > 100):
            raise ValueError(f"invalid min-speed: {s}")
        self.send("min-speed", s)
