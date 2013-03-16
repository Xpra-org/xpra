# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

YUV420P = 420
YUV422P = 422
YUV444P = 444

def get_subsampling_divs(pixel_format):
    # Return size dividers for the given pixel format
    #  (Y_w, Y_h), (U_w, U_h), (V_w, V_h)
    if pixel_format==YUV420P:
        return (1, 1), (2, 2), (2, 2)
    elif pixel_format==YUV422P:
        return (1, 1), (2, 1), (2, 1)
    elif pixel_format==YUV444P:
        return (1, 1), (1, 1), (1, 1)
    raise Exception("invalid pixel format: %s" % pixel_format)
