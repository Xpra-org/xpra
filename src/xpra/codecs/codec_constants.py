# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import weakref
from xpra.log import Logger
log = Logger("util")


def do_get_PIL_codings(PIL, attr="SAVE"):
    if PIL is None:
        return []
    pi = PIL.Image
    import os
    if os.environ.get("PIL_DEBUG", "0")=="1":
        log.info("enabling PIL.DEBUG")
        pi.DEBUG = 1
    pi.init()
    avalue = getattr(pi, attr)
    log("PIL.Image.%s=%s", attr, avalue)
    encodings = []
    test_options = ["png", "png/L", "png/P", "jpeg", "webp"]
    if attr=="OPEN":
        try:
            assert pi.PILLOW_VERSION>='2.8', "version %s leaks memory with webp" % pi.PILLOW_VERSION
        except Exception as e:
            log("Pillow support for opening webp images has been disabled: %s", e)
            test_options.remove("webp")
    for encoding in test_options:
        #strip suffix (so "png/L" -> "png")
        stripped = encoding.split("/")[0].upper()
        if stripped in avalue:
            encodings.append(encoding)
    log("do_get_PIL_codings(%s, %s)=%s", PIL, attr, encodings)
    return encodings

def get_PIL_encodings(PIL):
    return do_get_PIL_codings(PIL, "SAVE")

def get_PIL_decodings(PIL):
    return do_get_PIL_codings(PIL, "OPEN")


#value: how much smaller the output is
LOSSY_PIXEL_FORMATS = {"YUV420P" : 2,
                       "YUV422P" : 1.5
                       }

PIXEL_SUBSAMPLING = {
         "YUV420P"   : ((1, 1), (2, 2), (2, 2)),
         "YUV422P"   : ((1, 1), (2, 1), (2, 1)),
         "YUV444P"   : ((1, 1), (1, 1), (1, 1)),
         "GBRP"      : ((1, 1), (1, 1), (1, 1)),
}
def get_subsampling_divs(pixel_format):
    # Return size dividers for the given pixel format
    #  (Y_w, Y_h), (U_w, U_h), (V_w, V_h)
    if pixel_format not in PIXEL_SUBSAMPLING:
        raise Exception("invalid pixel format: %s" % pixel_format)
    return PIXEL_SUBSAMPLING.get(pixel_format)


RGB_FORMATS = ("XRGB",
               "BGRX",
               "ARGB",
               "BGRA",
               "RGB")


class TransientCodecException(Exception):
    pass


class codec_spec(object):

    #I can't imagine why someone would have more than this many
    #encoders or csc modules active at the same time!
    WARN_LIMIT = 25

    def __init__(self, codec_class, codec_type="",
                    quality=100, speed=100,
                    setup_cost=50, cpu_cost=100, gpu_cost=0,
                    min_w=1, min_h=1, max_w=4*1024, max_h=4*1024,
                    can_scale=False,
                    score_boost=0,
                    width_mask=0xFFFF, height_mask=0xFFFF):
        self.codec_class = codec_class          #ie: xpra.codecs.enc_x264.encoder.Encoder
        self.codec_type = codec_type            #ie: "nvenc"
        self.quality = quality
        self.speed = speed
        self.setup_cost = setup_cost
        self.cpu_cost = cpu_cost
        self.gpu_cost = gpu_cost
        self.score_boost = score_boost
        self.min_w = min_w
        self.min_h = min_h
        self.max_w = max_w
        self.max_h = max_h
        self.width_mask = width_mask
        self.height_mask = height_mask
        self.can_scale = can_scale
        self.max_instances = 0
        self._exported_fields = ["codec_class", "codec_type",
                        "quality", "speed",
                        "setup_cost", "cpu_cost", "gpu_cost", "score_boost",
                        "min_w", "min_h", "max_w", "max_h",
                        "width_mask", "height_mask",
                        "can_scale",
                        "max_instances"]
        #not exported:
        self.instances = weakref.WeakKeyDictionary()
        self._all_fields = list(self._exported_fields)+["instances"]


    def make_instance(self):
        cur = self.get_instance_count()
        if (self.max_instances>0 and cur>=self.max_instances) or cur>=codec_spec.WARN_LIMIT:
            log.warn("Warning: already %s active instances of %s: %s", cur, self.codec_class, list(self.instances.keys()))
            from xpra.util import dump_references
            dump_references(log, self.instances.keys())
        else:
            log("make_instance() %s - instance count=%s", self.codec_type, cur)
        v = self.codec_class()
        self.instances[v] = True
        return v


    def get_instance_count(self):
        return len(list(self.instances.keys()))

    def to_dict(self):
        d = {}
        for k in self._exported_fields:
            d[k] = getattr(self, k)
        return d

    def get_runtime_factor(self):
        #a cost multiplier that some encoder may want to override
        #1.0 means no change:
        mi = self.max_instances
        ic = len(self.instances.keys())
        if ic==0 or mi==0:
            return 1.0                      #no problem
        if ic>=mi:
            return 0                        #not possible
        if mi>0 and ic>0:
            #squared slope: 50% utilisation -> value=0.75
            return max(0, 1.0 - (1.0*ic/mi)**2)
        return 1.0

    def __repr__(self):
        return "codec_spec(%s)" % self.info()

    def info(self):
        try:
            s = str(self.codec_class)
            #regexp it?
            p = s.find("xpra.codecs.")
            if p>=0:
                s = s[p+len("xpra.codecs."):]
            p = s.find(".encoder.")
            if p<0:
                p = s.find(".colorspace_converter.")
            if p>0:
                s = s[:p]
            if s=="csc_%s" % self.codec_type:
                return self.codec_type
            if s=="enc_%s" % self.codec_type:
                return self.codec_type
            if self.codec_type==s:
                return self.codec_type
            return "%s:%s" % (self.codec_type, s)
        except:
            return "%s" % (self.codec_type or self.codec_class)


class video_codec_spec(codec_spec):

    def __init__(self, encoding=None, output_colorspaces=None, has_lossless_mode=False, **kwargs):
        codec_spec.__init__(self, **kwargs)
        self.encoding = encoding                        #ie: "h264"
        self.output_colorspaces = output_colorspaces    #ie: ["YUV420P" : "YUV420P", ...]
        self.has_lossless_mode = has_lossless_mode
        self._exported_fields += ["encoding", "output_colorspaces"]


def main():
    from xpra.platform import init, clean
    try:
        init("Codec-Constants", "Codec Constants Info")
        import sys
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()

        try:
            from PIL import Image   #@UnresolvedImport @UnusedImport
            import PIL              #@UnresolvedImport
        except:
            PIL = None
        print("PIL encodings: %s" % ", ".join(get_PIL_encodings(PIL)))
        print("PIL decodings: %s" % ", ".join(get_PIL_decodings(PIL)))
    finally:
        #this will wait for input on win32:
        clean()

if __name__ == "__main__":
    main()
