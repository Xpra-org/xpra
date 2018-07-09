# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.log import Logger
log = Logger("client")
traylog = Logger("client", "tray")
keylog = Logger("client", "keyboard")
workspacelog = Logger("client", "workspace")
iconlog = Logger("client", "icon")
screenlog = Logger("client", "screen")
scalinglog = Logger("scaling")
netlog = Logger("network")
bandwidthlog = Logger("bandwidth")


from xpra.codecs.loader import load_codecs, codec_versions, has_codec, get_codec, PREFERED_ENCODING_ORDER, PROBLEMATIC_ENCODINGS
from xpra.codecs.video_helper import getVideoHelper, NO_GFX_CSC_OPTIONS
from xpra.scripts.config import parse_bool_or_int
from xpra.net import compression
from xpra.util import envint, envbool, updict
from xpra.client.mixins.stub_client_mixin import StubClientMixin

B_FRAMES = envbool("XPRA_B_FRAMES", True)
PAINT_FLUSH = envbool("XPRA_PAINT_FLUSH", True)
MAX_SOFT_EXPIRED = envint("XPRA_MAX_SOFT_EXPIRED", 5)
SEND_TIMESTAMPS = envbool("XPRA_SEND_TIMESTAMPS", False)
VIDEO_MAX_SIZE = tuple(int(x) for x in os.environ.get("XPRA_VIDEO_MAX_SIZE", "4096,4096").replace("x", ",").split(","))


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
        self.video_scaling = 0
        self.video_max_size = VIDEO_MAX_SIZE

        self.server_encodings = []
        self.server_core_encodings = []
        self.server_encodings_problematic = PROBLEMATIC_ENCODINGS
        self.server_encodings_with_speed = ()
        self.server_encodings_with_quality = ()
        self.server_encodings_with_lossless_mode = ()
        self.server_auto_video_encoding = False

        #what we told the server about our encoding defaults:
        self.encoding_defaults = {}


    def init(self, opts, _extra_args=[]):
        self.allowed_encodings = opts.encodings
        self.encoding = opts.encoding
        self.video_scaling = parse_bool_or_int("video-scaling", opts.video_scaling)
        self.quality = opts.quality
        self.min_quality = opts.min_quality
        self.speed = opts.speed
        self.min_speed = opts.min_speed
        #until we add the ability to choose decoders, use all of them:
        #(and default to non grahics card csc modules if not specified)
        load_codecs(encoders=False)
        vh = getVideoHelper()
        vh.set_modules(video_decoders=opts.video_decoders, csc_modules=opts.csc_modules or NO_GFX_CSC_OPTIONS)
        vh.init()


    def cleanup(self):
        try:
            getVideoHelper().cleanup()
        except:
            log.error("error on video cleanup", exc_info=True)


    def get_caps(self):
        caps = {
            #legacy (not needed in 1.0 - can be dropped soon):
            "generic-rgb-encodings"     : True,
            "encodings"                 : self.get_encodings(),
            "encodings.core"            : self.get_core_encodings(),
            "encodings.window-icon"     : self.get_window_icon_encodings(),
            "encodings.cursor"          : self.get_cursor_encodings(),
            }
        updict(caps, "batch",           self.get_batch_caps())
        updict(caps, "encoding",        self.get_encodings_caps())
        return caps

    def parse_server_capabilities(self):
        c = self.server_capabilities
        self.server_encodings = c.strlistget("encodings")
        self.server_core_encodings = c.strlistget("encodings.core", self.server_encodings)
        self.server_encodings_problematic = c.strlistget("encodings.problematic", PROBLEMATIC_ENCODINGS)  #server is telling us to try to avoid those
        self.server_encodings_with_speed = c.strlistget("encodings.with_speed", ("h264",)) #old servers only supported x264
        self.server_encodings_with_quality = c.strlistget("encodings.with_quality", ("jpeg", "webp", "h264"))
        self.server_encodings_with_lossless_mode = c.strlistget("encodings.with_lossless_mode", ())
        self.server_auto_video_encoding = c.boolget("auto-video-encoding")
        e = c.strget("encoding")
        if e:
            if self.encoding and e!=self.encoding:
                if self.encoding not in self.server_core_encodings:
                    log.warn("server does not support %s encoding and has switched to %s", self.encoding, e)
                else:
                    log.info("server is using %s encoding instead of %s", e, self.encoding)
            self.encoding = e
        return True


    def get_batch_caps(self):
        #batch options:
        caps = {}
        for bprop in ("always", "min_delay", "max_delay", "delay", "max_events", "max_pixels", "time_unit"):
            evalue = os.environ.get("XPRA_BATCH_%s" % bprop.upper())
            if evalue:
                try:
                    caps["batch.%s" % bprop] = int(evalue)
                except:
                    log.error("Error: invalid environment value for %s: %s", bprop, evalue)
        log("get_batch_caps()=%s", caps)
        return caps

    def get_encodings_caps(self):
        if B_FRAMES:
            video_b_frames = ["h264"]   #only tested with dec_avcodec2
        else:
            video_b_frames = []
        caps = {
            "flush"                     : PAINT_FLUSH,
            "scaling.control"           : self.video_scaling,
            "client_options"            : True,
            "csc_atoms"                 : True,
            #TODO: check for csc support (swscale only?)
            "video_reinit"              : True,
            "video_scaling"             : True,
            "video_b_frames"            : video_b_frames,
            "video_max_size"            : self.video_max_size,
            "webp_leaks"                : False,
            "transparency"              : self.has_transparency(),
            "rgb24zlib"                 : True,
            "max-soft-expired"          : MAX_SOFT_EXPIRED,
            "send-timestamps"           : SEND_TIMESTAMPS,
            "supports_delta"            : tuple(x for x in ("png", "rgb24", "rgb32") if x in self.get_core_encodings()),
            }
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
            # set the default to "high10" for I420/YUV420P
            # as the python client always supports all the profiles
            # whereas on the server side, the default is baseline to accomodate less capable clients.
            # I422/YUV422P requires high422, and
            # I444/YUV444P requires high444,
            # so we don't bother specifying anything for those two.
            for old_csc_name, csc_name, default_profile in (
                        ("I420", "YUV420P", "high10"),
                        ("I422", "YUV422P", ""),
                        ("I444", "YUV444P", "")):
                profile = default_profile
                #try with the old prefix (X264) as well as the more correct one (H264):
                for H264_NAME in ("X264", "H264"):
                    profile = os.environ.get("XPRA_%s_%s_PROFILE" % (H264_NAME, old_csc_name), profile)
                    profile = os.environ.get("XPRA_%s_%s_PROFILE" % (H264_NAME, csc_name), profile)
                if profile:
                    #send as both old and new names:
                    for h264_name in ("x264", "h264"):
                        caps["%s.%s.profile" % (h264_name, old_csc_name)] = profile
                        caps["%s.%s.profile" % (h264_name, csc_name)] = profile
            log("x264 encoding options: %s", str([(k,v) for k,v in caps.items() if k.startswith("x264.")]))
        iq = max(self.min_quality, self.quality)
        if iq<0:
            iq = 70
        caps["initial_quality"] = iq
        log("encoding capabilities: %s", caps)
        return caps

    def get_encodings(self):
        """
            Unlike get_core_encodings(), this method returns "rgb" for both "rgb24" and "rgb32".
            That's because although we may support both, the encoding chosen is plain "rgb",
            and the actual encoding used ("rgb24" or "rgb32") depends on the window's bit depth.
            ("rgb32" if there is an alpha channel, and if the client supports it)
        """
        cenc = self.get_core_encodings()
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
        e = ["premult_argb32", "default"]
        if "png" in self.get_core_encodings():
            e.append("png")
        return e

    def do_get_core_encodings(self):
        """
            This method returns the actual encodings supported.
            ie: ["rgb24", "vp8", "webp", "png", "png/L", "png/P", "jpeg", "jpeg2000", "h264", "vpx"]
            It is often overriden in the actual client class implementations,
            where extra encodings can be added (generally just 'rgb32' for transparency),
            or removed if the toolkit implementation class is more limited.
        """
        #we always support rgb:
        core_encodings = ["rgb24", "rgb32"]
        for codec in ("dec_pillow", "dec_webp"):
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
        core_encodings = [x for x in PREFERED_ENCODING_ORDER if x in set(core_encodings) and x in self.allowed_encodings]
        return core_encodings

    def set_encoding(self, encoding):
        log("set_encoding(%s)", encoding)
        if encoding=="auto":
            assert self.server_auto_video_encoding
            self.encoding = ""
        else:
            assert encoding in self.get_encodings(), "encoding %s is not supported!" % encoding
            assert encoding in self.server_encodings, "encoding %s is not supported by the server! (only: %s)" % (encoding, self.server_encodings)
        self.encoding = encoding
        self.send("encoding", self.encoding)

    def send_quality(self):
        q = self.quality
        log("send_quality() quality=%s", q)
        assert q==-1 or (q>=0 and q<=100), "invalid quality: %s" % q
        self.send("quality", q)

    def send_min_quality(self):
        q = self.min_quality
        log("send_min_quality() min-quality=%s", q)
        assert q==-1 or (q>=0 and q<=100), "invalid min-quality: %s" % q
        self.send("min-quality", q)

    def send_speed(self):
        s = self.speed
        log("send_speed() min-speed=%s", s)
        assert s==-1 or (s>=0 and s<=100), "invalid speed: %s" % s
        self.send("speed", s)

    def send_min_speed(self):
        s = self.min_speed
        log("send_min_speed() min-speed=%s", s)
        assert s==-1 or (s>=0 and s<=100), "invalid min-speed: %s" % s
        self.send("min-speed", s)
