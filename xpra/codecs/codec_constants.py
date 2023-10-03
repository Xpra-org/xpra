# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2012-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from weakref import WeakSet
from typing import Any, Tuple, Union, Dict, Set

from xpra.util import envint, typedict


FAST_DECODE_MIN_SPEED : int = envint("XPRA_FAST_DECODE_MIN_SPEED", 70)


#note: this is just for defining the order of encodings,
#so we have both core encodings (rgb24/rgb32) and regular encodings (rgb) in here:
PREFERRED_ENCODING_ORDER : Tuple[str, ...] = (
    "h264", "vp9", "vp8", "mpeg4",
    "mpeg4+mp4", "h264+mp4", "vp8+webm", "vp9+webm",
    "png", "png/P", "png/L", "webp", "avif",
    "rgb", "rgb24", "rgb32", "jpeg", "jpega",
    "h265", "av1",
    "scroll",
    "grayscale",
    "stream",
    )
STREAM_ENCODINGS : Tuple[str,...] = (
    "h264", "vp9", "vp8", "mpeg4",
    "mpeg4+mp4", "h264+mp4", "vp8+webm", "vp9+webm",
    "h265", "av1",
    )

#encoding order for edges (usually one pixel high or wide):
EDGE_ENCODING_ORDER : Tuple[str, ...] = (
    "rgb24", "rgb32",
    "png", "webp",
    "png/P", "png/L", "rgb", "jpeg", "jpega",
    )

HELP_ORDER : Tuple[str, ...] = (
    "auto",
    "stream",
    "grayscale",
    "h264", "h265", "av1", "vp8", "vp9", "mpeg4",
    "png", "png/P", "png/L", "webp", "avif",
    "rgb", "jpeg", "jpega",
    "scroll",
    )


#value: how much smaller the output is
LOSSY_PIXEL_FORMATS : Dict[str,Union[float, int]] = {
    "NV12"    : 2,
    "YUV420P" : 2,
    "YUV422P" : 1.5,
    }

def get_plane_name(pixel_format : str="YUV420P", index : int=0) -> str:
    return {
        "NV12" : ("Y", "UV"),
        }.get(pixel_format, list(pixel_format))[index]


PIXEL_SUBSAMPLING : Dict[str,Tuple] = {
    #NV12 is actually subsampled horizontally too - just like YUV420P
    #(but combines U and V planes so the resulting rowstride for the UV plane is the same as the Y plane):
    "NV12"      : ((1, 1), (1, 2)),
    "YUV420P"   : ((1, 1), (2, 2), (2, 2)),
    "YUV422P"   : ((1, 1), (2, 1), (2, 1)),
    "YUV444P"   : ((1, 1), (1, 1), (1, 1)),
    "YUV400P"   : ((1, 1), ),
    "GBRP"      : ((1, 1), (1, 1), (1, 1)),
    "GBRP9LE"   : ((1, 1), (1, 1), (1, 1)),
    "GBRP10"    : ((1, 1), (1, 1), (1, 1)),
    "YUV444P10" : ((1, 1), (1, 1), (1, 1)),
    "YUV444P16" : ((1, 1), (1, 1), (1, 1)),
}
def get_subsampling_divs(pixel_format:str) -> Tuple[Tuple[int,int],...]:
    # Return size dividers for the given pixel format
    #  (Y_w, Y_h), (U_w, U_h), (V_w, V_h)
    if pixel_format not in PIXEL_SUBSAMPLING:
        raise ValueError(f"invalid pixel format: {pixel_format!r}")
    return PIXEL_SUBSAMPLING[pixel_format]

def preforder(encodings) -> Tuple[str, ...]:
    encs : Set[str] = set(encodings)
    return tuple(x for x in PREFERRED_ENCODING_ORDER if x in encs)


def get_profile(options:typedict, encoding:str="h264", csc_mode:str="YUV420P", default_profile:str="constrained-baseline") -> str:
    return (
        options.strget(f"{encoding}.{csc_mode}.profile") or
        options.strget(f"{encoding}.profile") or
        os.environ.get(f"XPRA_{encoding.upper()}_{csc_mode}_PROFILE") or
        os.environ.get(f"XPRA_{encoding.upper()}_PROFILE") or
        default_profile
        )

def get_x264_quality(pct:int, profile:str="") -> int:
    if pct>=100 and profile=="high444":
        return 0
    return 50 - (min(100, max(0, pct)) * 49 // 100)

def get_x264_preset(speed:int=50, fast_decode:bool=False) -> int:
    if fast_decode:
        speed = max(FAST_DECODE_MIN_SPEED, speed)
    if speed > 99:
        #only allow "ultrafast" if pct > 99
        return 0
    return 5 - max(0, min(4, speed // 20))


RGB_FORMATS : Tuple[str, ...] = (
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


class _codec_spec:

    def __init__(self, codec_class, codec_type : str="",
                    quality:int=50, speed:int=50,
                    size_efficiency:int=50,
                    setup_cost:int=50, cpu_cost:int=100, gpu_cost:int=0,
                    min_w:int=1, min_h:int=1, max_w:int=4*1024, max_h:int=4*1024,
                    can_scale:bool=False,
                    score_boost:int=0,
                    width_mask:int=0xFFFF, height_mask:int=0xFFFF):
        self.codec_class = codec_class          #ie: xpra.codecs.x264.encoder.Encoder
        self.codec_type : str = codec_type            #ie: "nvenc"
        self.quality : int = quality
        self.speed : int = speed
        self.size_efficiency : int = size_efficiency
        self.setup_cost : int = setup_cost
        self.cpu_cost : int = cpu_cost
        self.gpu_cost : int = gpu_cost
        self.score_boost : int = score_boost
        self.min_w : int = min_w
        self.min_h : int = min_h
        self.max_w : int = max_w
        self.max_h : int = max_h
        self.width_mask : int = width_mask
        self.height_mask : int = height_mask
        self.can_scale : bool = can_scale
        self.max_instances : int = 0
        self._exported_fields = [
            "codec_class", "codec_type",
            "quality", "speed",
            "setup_cost", "cpu_cost", "gpu_cost", "score_boost",
            "min_w", "min_h", "max_w", "max_h",
            "width_mask", "height_mask",
            "can_scale",
            "max_instances",
            ]
        #not exported:
        self.instances : WeakSet[Any] = WeakSet()
        self._all_fields = list(self._exported_fields)+["instances"]


    def make_instance(self) -> object:
        # pylint: disable=import-outside-toplevel
        #I can't imagine why someone would have more than this many
        #encoders or csc modules active at the same time!
        WARN_LIMIT = envint("XPRA_CODEC_INSTANCE_COUNT_WARN", 25)
        from xpra.log import Logger
        log = Logger("encoding")
        cur = self.get_instance_count()
        if 0<self.max_instances<cur or cur>=WARN_LIMIT:
            instances = tuple(self.instances)
            log.warn(f"Warning: already {cur} active instances of {self.codec_class}:")
            try:
                import gc
                for i in instances:
                    refs = gc.get_referrers(i)
                    log.warn(f" referers({i})={refs}")
            except Exception:
                pass
        else:
            log("make_instance() %s - instance count=%s", self.codec_type, cur)
        v = self.codec_class()
        self.instances.add(v)
        return v


    def get_instance_count(self) -> int:
        return len(self.instances)

    def to_dict(self) -> Dict[str,Any]:
        d = {}
        for k in self._exported_fields:
            d[k] = getattr(self, k)
        return d

    def get_runtime_factor(self) -> float:
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
            return max(0.0, 1.0 - (1.0*ic/mi)**2)
        return 1.0


class video_spec(_codec_spec):

    def __init__(self, encoding : str, input_colorspace : str, output_colorspaces : Tuple, has_lossless_mode : bool,
                 codec_class, codec_type : str, min_w:int=2, min_h:int=2, **kwargs):
        self.encoding : str = encoding                        #ie: "h264"
        self.input_colorspace : str = input_colorspace
        self.output_colorspaces = output_colorspaces    #ie: ["YUV420P" : "YUV420P", ...]
        self.has_lossless_mode : bool = has_lossless_mode
        super().__init__(codec_class, codec_type, min_w=min_w, min_h=min_h, **kwargs)
        self._exported_fields += ["encoding", "input_colorspace", "output_colorspaces", "has_lossless_mode"]

    def __repr__(self):
        return f"{self.codec_type}({self.input_colorspace} to {self.encoding})"


class csc_spec(_codec_spec):

    def __init__(self, input_colorspace:str, output_colorspace:str, codec_class, codec_type:str, **kwargs):
        self.input_colorspace : str = input_colorspace
        self.output_colorspace : str = output_colorspace
        super().__init__(codec_class, codec_type, **kwargs)
        self._exported_fields += ["input_colorspace", "output_colorspace"]

    def __repr__(self):
        return f"{self.codec_type}({self.input_colorspace} to {self.output_colorspace})"


def main():
    # pylint: disable=import-outside-toplevel
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
