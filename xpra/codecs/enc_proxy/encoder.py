# This file is part of Xpra.
# Copyright (C) 2014-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from collections import deque

from xpra.codecs.image_wrapper import ImageWrapper
from xpra.util import typedict
from xpra.os_util import memoryview_to_bytes
from xpra.log import Logger

log = Logger("encoder", "proxy")


def get_version():
    return (0, 2)

def get_type():
    return "proxy"

def get_info():
    return {"version"   : get_version()}

def get_encodings():
    return ("proxy", )

def init_module():
    log("enc_proxy.init_module()")

def cleanup_module():
    log("enc_proxy.cleanup_module()")


class Encoder:
    """
        This is a "fake" encoder which just forwards
        the raw pixels and the metadata that goes with it.
    """

    def init_context(self, encoding, width, height, src_format, options=None):
        options = typedict(options or {})
        self.encoding = encoding
        self.width = width
        self.height = height
        self.src_format = src_format
        self.dst_formats = options.strtupleget("dst-formats")
        self.last_frame_times = deque(maxlen=200)
        self.frames = 0
        self.time = 0
        self.first_frame_timestamp = 0

    def is_ready(self):
        return True

    def get_info(self) -> dict:
        info = get_info()
        if self.src_format is None:
            return info
        info.update({
            "frames"    : self.frames,
            "width"     : self.width,
            "height"    : self.height,
            "encoding"  : self.encoding,
            "src_format": self.src_format,
            "dst_formats" : self.dst_formats,
            "version"   : get_version(),
            })
        #calculate fps:
        now = monotonic()
        last_time = now
        cut_off = now-10.0
        f = 0
        for v in tuple(self.last_frame_times):
            if v>cut_off:
                f += 1
                last_time = min(last_time, v)
        if f>0 and last_time<now:
            info["fps"] = int(0.5+f/(now-last_time))
        return info

    def __repr__(self):
        if self.src_format is None:
            return "proxy_encoder(uninitialized)"
        return "proxy_encoder(%s - %sx%s)" % (self.src_format, self.width, self.height)

    def is_closed(self):
        return self.src_format is None

    def get_encoding(self):
        return self.encoding

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_type(self):
        return "proxy"

    def get_src_format(self):
        return self.src_format

    def clean(self):
        self.width = 0
        self.height = 0
        self.src_format = None
        self.encoding = ""
        self.src_format = ""
        self.dst_formats = []
        self.last_frame_times = []
        self.frames = 0
        self.time = 0
        self.first_frame_timestamp = 0

    def compress_image(self, image, options=None):
        log("compress_image(%s, %s)", image, options)
        #pass the pixels as they are
        assert image.get_planes()==ImageWrapper.PACKED, "invalid number of planes: %s" % image.get_planes()
        pixels = image.get_pixels()
        assert pixels, "failed to get pixels from %s" % image
        #info used by proxy encoder:
        client_options = {
                "proxy"     : True,
                "frame"     : self.frames,
                "pts"       : image.get_timestamp()-self.first_frame_timestamp,
                "timestamp" : image.get_timestamp(),
                "rowstride" : image.get_rowstride(),
                "depth"     : image.get_depth(),
                "rgb_format": image.get_pixel_format(),
                #pass-through encoder options:
                "options"   : options or {},
                }
        if self.frames==0:
            self.first_frame_timestamp = image.get_timestamp()
            #must pass dst_formats so the proxy can instantiate the video encoder
            #with the correct CSC config:
            client_options["dst_formats"] = self.dst_formats
        log("compress_image(%s, %s) returning %s bytes and options=%s", image, options, len(pixels), client_options)
        self.last_frame_times.append(monotonic())
        self.frames += 1
        return  memoryview_to_bytes(pixels[:]), client_options
