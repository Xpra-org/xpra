# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.codec_constants import codec_spec

COLORSPACES = ("YUV420P", "YUV422P", "BGRA")

def get_input_colorspaces():
    return COLORSPACES

def get_output_colorspaces(input_colorspace):
    return [x for x in COLORSPACES if x!=input_colorspace]

def get_spec(in_colorspace, out_colorspace):
    assert in_colorspace in COLORSPACES, "invalid input colorspace: %s (must be one of %s)" % (in_colorspace, COLORSPACES)
    assert out_colorspace in COLORSPACES, "invalid output colorspace: %s (must be one of %s)" % (out_colorspace, COLORSPACES)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    return codec_spec(ColorspaceConverter, 100, 100, 10, 100, 0, 50, 4096, 4096, 4096*4096, False)


class ColorspaceConverter(object):

    def init_context(self, src_width, src_height, src_format,
                           dst_width, dst_height, dst_format):    #@DuplicatedSignature
        raise Exception("this is a fake encoder!")
