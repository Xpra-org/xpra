# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cv2
import numpy

from xpra.log import Logger
log = Logger("csc", "opencv")

from xpra.codecs.codec_constants import csc_spec
from xpra.codecs.image_wrapper import ImageWrapper
from xpra.util import print_nested_dict
from xpra.os_util import _memoryview


def roundup(n, m):
    return (n + m - 1) & ~(m - 1)


def init_module():
    #nothing to do!
    log("csc_opencv.init_module()")

def cleanup_module():
    log("csc_opencv.cleanup_module()")

def get_type():
    return "opencv"

def get_version():
    v = cv2.__version__
    #some Debian versions ship with a bogus version string,
    #ie: "$Rev: 4557 $"
    p = v.split("$")
    if len(p)==3:
        v = p[1]
        p = v.split("Rev:")
        if len(p)==2:
            v = "r"+p[1].strip()
    return v

def get_info():
    return {
            "version"   : get_version(),
            }


FLAG_STR = {}
CONVERSIONS = {}
for rgb_fmt, conv in {
                      "RGB"     : ("YUV2RGB_I420",  "RGB2YUV_I420"),
                      "RGBX"    : ("YUV2RGBA_I420", "RGBA2YUV_I420"),
                      "RGBA"    : ("YUV2RGBA_I420", "RGBA2YUV_I420"),
                      "BGR"     : ("YUV2BGR_I420",  "BGR2YUV_I420"),
                      "BGRA"    : ("YUV2BGRA_I420", "BGRA2YUV_I420"),
                      "BGRX"    : ("YUV2BGRA_I420", "BGRA2YUV_I420"),
                      }.items():
    fromyuv, toyuv = conv
    for src_fmt, dst_fmt, conv_const in (
                                         ("YUV420P",    rgb_fmt,    fromyuv),
                                         (rgb_fmt,      "YUV420P",  toyuv),
                                         ):
        f = "COLOR_%s" % conv_const
        v = getattr(cv2, f, None)
        if v is not None:
            FLAG_STR[int(v)] = conv_const
            CONVERSIONS.setdefault(src_fmt, {})[dst_fmt] = int(v)
log("csc_opencv FLAGS: %s", FLAG_STR)
log("csc_opencv CONVERSIONS:")
print_nested_dict(CONVERSIONS, print_fn=log)


def get_input_colorspaces():
    #we don't handle planar input yet:
    return [x for x in CONVERSIONS.keys() if x!="YUV420P"]

def get_output_colorspaces(input_colorspace):
    return CONVERSIONS[input_colorspace]

def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in CONVERSIONS, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, get_input_colorspaces())
    out_cs = CONVERSIONS[in_colorspace]
    assert out_colorspace in out_cs, "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, out_cs)
    #low score as this should be used as fallback only:
    return csc_spec(ColorspaceConverter, codec_type=get_type(), quality=50, speed=0, setup_cost=40, min_w=2, min_h=2, max_w=16*1024, max_h=16*1024, can_scale=False)


class ColorspaceConverter(object):

    def init_context(self, src_width, src_height, src_format, dst_width, dst_height, dst_format, speed=100):
        assert src_format in get_input_colorspaces(), "invalid input colorspace: %s (must be one of %s)" % (src_format, get_input_colorspaces())
        assert dst_format in get_output_colorspaces(src_format), "invalid output colorspace: %s (must be one of %s)" % (dst_format, get_output_colorspaces(src_format))
        log("csc_opencv.ColorspaceConverter.init_context%s", (src_width, src_height, src_format, dst_width, dst_height, dst_format, speed))
        assert src_width==dst_width and src_height==dst_height
        self.width = src_width
        self.height = src_height
        self.src_format = src_format
        self.dst_format = dst_format
        global CONVERSIONS
        assert src_format in CONVERSIONS, "invalid input colorspace: %s" % src_format
        conv = CONVERSIONS[src_format]
        assert dst_format in conv, "invalid output colorspace: %s" % dst_format
        self.flag = conv[dst_format]
        log("csc_opencv: %s to %s=%s (%i)", src_format, dst_format, FLAG_STR.get(self.flag, self.flag), self.flag)

    def clean(self):                        #@DuplicatedSignature
        #overzealous clean is cheap!
        self.width = 0
        self.height = 0
        self.src_format = ""
        self.dst_format = ""
        self.flag = None

    def is_closed(self):
        return self.flag is None

    def get_info(self):      #@DuplicatedSignature
        return {
                "width"     : self.width,
                "height"    : self.height,
                "function"  : FLAG_STR.get(self.flag, self.flag),
                }

    def __repr__(self):
        return "csc_opencv(%s to %s - %sx%s)" % (self.src_format, self.dst_format, self.width, self.height)

    def __dealloc__(self):                  #@DuplicatedSignature
        self.clean()

    def get_src_width(self):
        return self.width

    def get_src_height(self):
        return self.height

    def get_src_format(self):
        return self.src_format

    def get_dst_width(self):
        return self.width

    def get_dst_height(self):
        return self.height

    def get_dst_format(self):
        return self.dst_format

    def get_type(self):                     #@DuplicatedSignature
        return  "opencv"


    def convert_image(self, image):
        iplanes = image.get_planes()
        w = image.get_width()
        h = image.get_height()
        assert w>=self.width, "invalid image width: %s (minimum is %s)" % (w, self.width)
        assert h>=self.height, "invalid image height: %s (minimum is %s)" % (h, self.height)
        pixels = image.get_pixels()
        assert pixels, "failed to get pixels from %s" % image
        input_stride = image.get_rowstride()
        log("convert_image(%s) input=%s, strides=%s", image, len(pixels), input_stride)
        assert iplanes==ImageWrapper.PACKED, "invalid input format: %s planes" % iplanes
        Bpp = len(self.src_format)
        if _memoryview and isinstance(pixels, _memoryview):
            na = numpy.asarray(pixels, numpy.uint8)
        else:
            na = numpy.frombuffer(pixels, numpy.uint8)
        #stride in number of pixels per line:
        stride = input_stride//Bpp
        iwidth = self.width     #roundup(self.width, 2)
        iheight = self.height   #roundup(self.height, 2)
        if len(pixels)!=input_stride*iheight:
            #ensure the input matches the array size we want:
            log("resizing numpy array from %s to %s (%i*%i*%i)", na.shape, (iwidth*iheight*Bpp), iwidth, iheight, Bpp)
            rgb = numpy.resize(na, (stride*iheight*Bpp))
        else:
            rgb = na
        #reshape the numpy array into the format expected by opencv:
        cv_in_buf = rgb.reshape((iheight, stride, Bpp))
        if iheight%2!=0 or stride%2!=0:
            #we need to trim the array to use even dimensions for opencv:
            nwidth = stride&0xFFFE
            nheight = iheight&0xFFFE
            #copy into a new array one line at a time:
            resized = numpy.empty((nheight, nwidth, Bpp), numpy.uint8)
            for i in range(nheight):
                resized[i] = cv_in_buf[i][:nwidth]
            cv_in_buf = resized
            iwidth = nwidth
            iheight = nheight
        out = cv2.cvtColor(cv_in_buf, self.flag)
        log("cv2.cvtColor(%s bytes, %s)=%s", len(pixels), FLAG_STR.get(self.flag, self.flag), out.shape)
        #read the output buffer into a flat buffer, then split it into components:
        Ystride = iwidth
        Ustride = Vstride = Ystride//2
        flat_out = out.reshape(-1)
        Yend = (Ystride * h)
        Y = flat_out.data[:Yend]
        Uend = Yend + (Ustride*iheight//2)
        U = flat_out.data[Yend:Uend]
        Vend = Uend + (Vstride*iheight//2)
        V = flat_out.data[Uend:Vend]
        pixels = (Y, U, V)
        strides = (Ystride, Ustride, Vstride)
        planes = ImageWrapper._3_PLANES
        log("output strides: %s", strides)
        return ImageWrapper(0, 0, w, h, pixels, self.dst_format, 24, strides, planes)


def selftest(full=False):
    from xpra.codecs.codec_checks import testcsc
    from xpra.codecs.csc_opencv import colorspace_converter
    testcsc(colorspace_converter, full)
