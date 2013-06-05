# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.codecs.codec_constants import codec_spec

COLORSPACES = ("YUV420P", )
def get_colorspaces():
    return COLORSPACES

def get_spec(colorspace):
    assert colorspace in COLORSPACES, "invalid colorspace: %s (must be one of %s)" % (colorspace, COLORSPACES)
    #ratings: quality, speed, setup cost, cpu cost, gpu cost, latency, max_w, max_h, max_pixels
    return codec_spec(Encoder, quality=60, setup_cost=100, cpu_cost=10, gpu_cost=100)


class Encoder(object):

    def init_context(self, width, height, src_format, quality, speed, options):
        raise Exception("this is a fake encoder!")
