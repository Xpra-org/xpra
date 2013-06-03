# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

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


AVUTIL_ENUM_TO_COLORSPACE =  {
            0   : "YUV420P",
            2   : "RGB",
            3   : "BGR",
            4   : "YUV422P",
            5   : "YUV444P"}
COLORSPACE_TO_AVUTIL_ENUM = {}
for e, s in AVUTIL_ENUM_TO_COLORSPACE.items():
    COLORSPACE_TO_AVUTIL_ENUM[s] = e

def get_colorspace_from_avutil_enum(pixfmt):
    return AVUTIL_ENUM_TO_COLORSPACE.get(pixfmt)

def get_avutil_enum_from_colorspace(pixfmt):
    return COLORSPACE_TO_AVUTIL_ENUM.get(pixfmt)


RGB_FORMATS = ("XRGB",
               "BGRX",
               "ARGB",
               "BGRA",
               "RGB")


class codec_spec(object):

    def __init__(self, codec_class, quality, speed, setup_cost, cpu_cost, gpu_cost, latency, max_w, max_h, max_pixels, can_scale=False):
        self.codec_class = codec_class
        self.quality = quality
        self.speed = speed
        self.setup_cost = setup_cost
        self.cpu_cost = cpu_cost
        self.gpu_cost = gpu_cost
        self.latency = latency
        self.max_w = max_w
        self.max_h = max_h
        self.max_pixels = max_pixels
        self.can_scale = can_scale

    def can_handle(self, width, height):
        return self.max_w>=width and self.max_h>=height and self.max_pixels>(width*height)

    def __str__(self):
        return "codec_spec(%s)" % self.__dict__

    def __repr__(self):
        return "codec_spec(%s)" % self.codec_class
