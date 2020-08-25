# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.codecs.codec_constants import PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.loader import load_codec, codec_versions, has_codec, get_codec
from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS
from xpra.scripts.config import parse_bool_or_int
from xpra.net import compression
from xpra.util import envint, envbool, updict, csv, typedict
from xpra.client.mixins.stub_client_mixin import StubClientMixin
from xpra.log import Logger

log = Logger("client", "encoding")

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)
VIDEO_MAX_SIZE = tuple(int(x) for x in os.environ.get("XPRA_VIDEO_MAX_SIZE", "4096,4096").replace("x", ",").split(","))

#we assume that any server will support at least those:
DEFAULT_ENCODINGS = os.environ.get("XPRA_DEFAULT_ENCODINGS", "rgb32,rgb24,jpeg,png").split(",")


"""
Mixin for adding encodings to a client
"""
class Encodings(StubClientMixin):

    def __init__(self):
        StubClientMixin.__init__(self)
        self.allowed_encodings = []
        self.core_encodings = None
        self.encoding = None
        self.quality = -1
        self.min_quality = 0
        self.speed = 0
        self.min_speed = -1
        self.video_scaling = None
        self.video_max_size = VIDEO_MAX_SIZE

        self.server_encodings = []
        self.server_core_encodings = []
        self.server_encodings_problematic = PROBLEMATIC_ENCODINGS
        self.server_encodings_with_speed = ()
        self.server_encodings_with_quality = ()
        self.server_encodings_with_lossless_mode = ()

        #what we told the server about our encoding defaults:
        self.encoding_defaults = {}


    def init(self, opts):
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
        if "jpeg" in ae:
            #try to load the fast jpeg encoder:
            load_codec("dec_jpeg")
        if "webp" in ae:
            #try to load the fast webp encoder:
            load_codec("dec_webp")
        vh = getVideoHelper()
        vh.set_modules(video_decoders=opts.video_decoders, csc_modules=opts.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()


    def cleanup(self):
        try:
            getVideoHelper().cleanup()
        except Exception:
            log.error("error on video cleanup", exc_info=True)


    def init_authenticated_packet_handlers(self):
        self.add_packet_handler("encodings", self._process_encodings, False)


    def _process_encodings(self, packet):
        caps = typedict(packet[1])
        self._parse_server_capabilities(caps)


    def get_info(self):
        return {
            "encodings" : {
                "core"          : self.get_core_encodings(),
                "window-icon"   : self.get_window_icon_encodings(),
                "cursor"        : self.get_cursor_encodings(),
                "quality"       : self.quality,
                "min-quality"   : self.min_quality,
                "speed"         : self.speed,
                "min-speed"     : self.min_speed,
                "encoding"      : self.encoding or "auto",
                "video-scaling" : self.video_scaling if self.video_scaling is not None else "auto",
                },
            "server-encodings"  : self.server_core_encodings,
            }


    def get_caps(self) -> dict:
        caps = {
            "encodings"                 : self.get_encodings(),
            "encodings.core"            : self.get_core_encodings(),
            "encodings.window-icon"     : self.get_window_icon_encodings(),
            "encodings.cursor"          : self.get_cursor_encodings(),
            "encodings.packet"          : True,
            }
        updict(caps, "batch",           self.get_batch_caps())
        updict(caps, "encoding",        self.get_encodings_caps())
        return caps

    def parse_server_capabilities(self, caps : typedict) -> bool:
        self._parse_server_capabilities(caps)
        return True

    def _parse_server_capabilities(self, c):
        self.server_encodings = c.strtupleget("encodings", DEFAULT_ENCODINGS)
        self.server_core_encodings = c.strtupleget("encodings.core", self.server_encodings)
        #server is telling us to try to avoid those:
        self.server_encodings_problematic = c.strtupleget("encodings.problematic", PROBLEMATIC_ENCODINGS)
        #old servers only supported x264:
        self.server_encodings_with_speed = c.strtupleget("encodings.with_speed", ("h264",))
        self.server_encodings_with_quality = c.strtupleget("encodings.with_quality", ("jpeg", "webp", "h264"))
        self.server_encodings_with_lossless_mode = c.strtupleget("encodings.with_lossless_mode", ())
        e = c.strget("encoding")
        if e and not c.boolget("encodings.delayed"):
            if self.encoding and e!=self.encoding:
                if self.encoding not in self.server_core_encodings:
                    log.warn("server does not support %s encoding and has switched to %s", self.encoding, e)
                else:
                    log.info("server is using %s encoding instead of %s", e, self.encoding)
            self.encoding = e


    def get_batch_caps(self) -> dict:
        #batch options:
        caps = {}
        for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
            evalue = os.environ.get("XPRA_BATCH_%s" % bprop.upper())
            if evalue:
                try:
                    caps["batch.%s" % bprop] = int(evalue)
                except ValueError:
                    log.error("Error: invalid environment value for %s: %s", bprop, evalue)
        log("get_batch_caps()=%s", caps)
        return caps

    def get_encodings_caps(self) -> dict:
        if B_FRAMES:
            video_b_frames = ("h264", ) #only tested with dec_avcodec2
        else:
            video_b_frames = ()
        caps = {
            "flush"                     : PAINT_FLUSH,      #v4 servers assume this is available
            "video_scaling"             : True,             #v4 servers assume this is available
            "video_b_frames"            : video_b_frames,
            "video_max_size"            : self.video_max_size,
            "max-soft-expired"          : MAX_SOFT_EXPIRED,
            "send-timestamps"           : SEND_TIMESTAMPS,
            "supports_delta"            : tuple(x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()),
            }
        if self.video_scaling is not None:
            caps["scaling.control"] = self.video_scaling
        if self.encoding:
            caps[""] = self.encoding
        for k,v in codec_versions.items():
            caps["%s.version" % k] = v
        if self.quality>0:
            caps["quality"] = self.quality
        if self.min_quality>0:
            caps["min-quality"] = self.min_quality
        if self.speed>=0:
            caps["speed"] = self.speed
        if self.min_speed>=0:
            caps["min-speed"] = self.min_speed

        #generic rgb compression flags:
        for x in compression.ALL_COMPRESSORS:
            caps["rgb_%s" % x] = x in compression.get_enabled_compressors()
        #these are the defaults - when we instantiate a window,
        #we can send different values as part of the map event
        #these are the RGB modes we want (the ones we are expected to be able to paint with):
        rgb_formats = ["RGB", "RGBX", "RGBA"]
        caps["rgb_formats"] = rgb_formats
        #figure out which CSC modes (usually YUV) can give us those RGB modes:
        full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*rgb_formats)
        if has_codec("dec_webp"):
            if self.opengl_enabled:
                full_csc_modes["webp"] = ("BGRX", "BGRA", "RGBX", "RGBA")
            else:
                full_csc_modes["webp"] = ("BGRX", "BGRA", )
        log("supported full csc_modes=%s", full_csc_modes)
        caps["full_csc_modes"] = full_csc_modes

        if "h264" in self.get_core_encodings():
            # some profile options: "baseline", "main", "high", "high10", ...
            # set the default to "high10" for YUV420P
            # as the python client always supports all the profiles
            # whereas on the server side, the default is baseline to accomodate less capable clients.
            # YUV422P requires high422, and
            # YUV444P requires high444,
            # so we don't bother specifying anything for those two.
            h264_caps = {}
            for csc_name, default_profile in (
                        ("YUV420P", "high10"),
                        ("YUV422P", ""),
                        ("YUV444P", "")):
                profile = os.environ.get("XPRA_H264_%s_PROFILE" % (csc_name), default_profile)
                if profile:
                    h264_caps["%s.profile" % (csc_name)] = profile
            h264_caps["fast-decode"] = envbool("XPRA_X264_FAST_DECODE", False)
            log("x264 encoding options: %s", h264_caps)
            updict(caps, "h264", h264_caps)
        log("encoding capabilities: %s", caps)
        return caps

    def get_encodings(self):
        """
            Unlike get_core_encodings(), this method returns "rgb" for both "rgb24" and "rgb32".
            That's because although we may support both, the encoding chosen is plain "rgb",
            and the actual encoding used ("rgb24" or "rgb32") depends on the window's bit depth.
            ("rgb32" if there is an alpha channel, and if the client supports it)
        """
        cenc = list(self.get_core_encodings())
        if ("rgb24" in cenc or "rgb32" in cenc) and "rgb" not in cenc:
            cenc.append("rgb")
        return [x for x in PREFERED_ENCODING_ORDER if x in cenc and x not in ("rgb32", "rgb24")]

    def get_core_encodings(self):
        if self.core_encodings is None:
            self.core_encodings = self.do_get_core_encodings()
        return self.core_encodings

    def get_cursor_encodings(self):
        e = ["raw"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def get_window_icon_encodings(self):
        e = ["premult_argb32", "BGRA", "default"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def do_get_core_encodings(self):
        """
            This method returns the actual encodings supported.
            ie: ["rgb24", "vp8", "webp", "png", "png/L", "png/P", "jpeg", "h264", "vpx"]
            It is often overriden in the actual client class implementations,
            where extra encodings can be added (generally just 'rgb32' for transparency),
            or removed if the toolkit implementation class is more limited.
        """
        #we always support rgb:
        core_encodings = ["rgb24", "rgb32"]
        for codec in ("dec_pillow", "dec_webp", "dec_jpeg"):
            if has_codec(codec):
                c = get_codec(codec)
                for e in c.get_encodings():
                    if e not in core_encodings:
                        core_encodings.append(e)
        #we enable all the video decoders we know about,
        #what will actually get used by the server will still depend on the csc modes supported
        video_decodings = getVideoHelper().get_decodings()
        log("video_decodings=%s", video_decodings)
        for encoding in video_decodings:
            if encoding not in core_encodings:
                core_encodings.append(encoding)
        #remove duplicates and use prefered encoding order:
        core_encodings = [x for x in PREFERED_ENCODING_ORDER
                          if x in set(core_encodings) and x in self.allowed_encodings]
        return core_encodings

    def set_encoding(self, encoding):
        log("set_encoding(%s)", encoding)
        if encoding=="auto":
            self.encoding = ""
        else:
            assert encoding in self.get_encodings(), "encoding %s is not supported!" % encoding
            if encoding not in self.server_encodings:
                log.error("Error: encoding %s is not supported by the server", encoding)
                log.error(" the only encodings allowed are:")
                log.error(" %s", csv(self.server_encodings))
                return
        self.encoding = encoding
        self.send("encoding", self.encoding)

    def send_quality(self):
        q = self.quality
        log("send_quality() quality=%s", q)
        assert q==-1 or 0<=q<=100, "invalid quality: %s" % q
        self.send("quality", q)

    def send_min_quality(self):
        q = self.min_quality
        log("send_min_quality() min-quality=%s", q)
        assert q==-1 or 0<=q<=100, "invalid min-quality: %s" % q
        self.send("min-quality", q)

    def send_speed(self):
        s = self.speed
        log("send_speed() min-speed=%s", s)
        assert s==-1 or 0<=s<=100, "invalid speed: %s" % s
        self.send("speed", s)

    def send_min_speed(self):
        s = self.min_speed
        log("send_min_speed() min-speed=%s", s)
        assert s==-1 or 0<=s<=100, "invalid min-speed: %s" % s
        self.send("min-speed", s)
