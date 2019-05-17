# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import weakref


#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERED_ENCODING_ORDER = (
    "h264", "vp9", "vp8", "mpeg4",
    "mpeg4+mp4", "h264+mp4", "vp8+webm", "vp9+webm",
    "png", "png/P", "png/L", "webp",
    "rgb", "rgb24", "rgb32", "jpeg",
    "h265", "mpeg1", "mpeg2",
    )
#encoding order for edges (usually one pixel high or wide):
EDGE_ENCODING_ORDER = (
    "rgb24", "rgb32",
    "png", "webp",
    "png/P", "png/L", "rgb", "jpeg",
    )

HELP_ORDER = (
    "auto", "h264", "h265", "vp8", "vp9", "mpeg4",
    "png", "png/P", "png/L", "webp",
    "rgb", "jpeg",
    )

#those are currently so useless that we don't want the user to select them by mistake
PROBLEMATIC_ENCODINGS = ("h265", )


#value: how much smaller the output is
LOSSY_PIXEL_FORMATS = {
    "YUV420P" : 2,
    "YUV422P" : 1.5,
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


RGB_FORMATS = (
               "XRGB",
               "BGRX",
               "ARGB",
               "BGRA",
               "RGB",
               "BGR",
               "r210",
               )


class TransientCodecException(Exception):
    pass

class CodecStateException(Exception):
    pass


class _codec_spec(object):

    #I can't imagine why someone would have more than this many
    #encoders or csc modules active at the same time!
    WARN_LIMIT = 25

    def __init__(self, codec_class, codec_type="",
                    quality=50, speed=50,
                    size_efficiency=50,
                    setup_cost=50, cpu_cost=100, gpu_cost=0,
                    min_w=1, min_h=1, max_w=4*1024, max_h=4*1024,
                    can_scale=False,
                    score_boost=0,
                    width_mask=0xFFFF, height_mask=0xFFFF):
        self.codec_class = codec_class          #ie: xpra.codecs.enc_x264.encoder.Encoder
        self.codec_type = codec_type            #ie: "nvenc"
        self.quality = quality
        self.speed = speed
        self.size_efficiency = size_efficiency
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
        from xpra.log import Logger
        log = Logger("encoding")
        cur = self.get_instance_count()
        if (self.max_instances>0 and cur>=self.max_instances) or cur>=_codec_spec.WARN_LIMIT:
            instances = tuple(self.instances.keys())
            log.warn("Warning: already %s active instances of %s: %s",
                     cur, self.codec_class, instances)
            from xpra.util import dump_references
            dump_references(log, instances)
        else:
            log("make_instance() %s - instance count=%s", self.codec_type, cur)
        v = self.codec_class()
        self.instances[v] = True
        return v


    def get_instance_count(self):
        return len(self.instances)

    def to_dict(self):
        d = {}
        for k in self._exported_fields:
            d[k] = getattr(self, k)
        return d

    def get_runtime_factor(self):
        #a cost multiplier that some encoder may want to override
        #1.0 means no change:
        mi = self.max_instances
        ic = len(self.instances)
        if ic==0 or mi==0:
            return 1.0                      #no problem
        if ic>=mi:
            return 0                        #not possible
        if mi>0 and ic>0:
            #squared slope: 50% utilisation -> value=0.75
            return max(0, 1.0 - (1.0*ic/mi)**2)
        return 1.0


class video_spec(_codec_spec):

    def __init__(self, encoding, input_colorspace, output_colorspaces, has_lossless_mode,
                 codec_class, codec_type, **kwargs):
        self.encoding = encoding                        #ie: "h264"
        self.input_colorspace = input_colorspace
        self.output_colorspaces = output_colorspaces    #ie: ["YUV420P" : "YUV420P", ...]
        self.has_lossless_mode = has_lossless_mode
        _codec_spec.__init__(self, codec_class, codec_type, **kwargs)
        self._exported_fields += ["encoding", "input_colorspace", "output_colorspaces", "has_lossless_mode"]

    def __repr__(self):
        return "%s(%s to %s)" % (self.codec_type, self.input_colorspace, self.encoding)


class csc_spec(_codec_spec):

    def __init__(self, input_colorspace, output_colorspace, codec_class, codec_type, **kwargs):
        self.input_colorspace = input_colorspace
        self.output_colorspace = output_colorspace
        _codec_spec.__init__(self, codec_class, codec_type, **kwargs)
        self._exported_fields += ["input_colorspace", "output_colorspace"]

    def __repr__(self):
        return "%s(%s to %s)" % (self.codec_type, self.input_colorspace, self.output_colorspace)


def main():
    from xpra.platform import program_context
    with program_context("Codec-Constants", "Codec Constants Info"):
        import sys
        from xpra.log import Logger
        log = Logger("encoding")
        if "-v" in sys.argv or "--verbose" in sys.argv:
            log.enable_debug()
        log.info("LOSSY_PIXEL_FORMATS=%s", LOSSY_PIXEL_FORMATS)
        log.info("PIXEL_SUBSAMPLING=%s", PIXEL_SUBSAMPLING)
        log.info("RGB_FORMATS=%s", RGB_FORMATS)


if __name__ == "__main__":
    main()
