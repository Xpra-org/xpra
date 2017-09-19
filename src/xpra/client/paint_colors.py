#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


DEFAULT_BOX_COLORS = {
    b"png"      : "yellow",
    b"h264"     : "blue",
    b"vp8"      : "green",
    b"rgb24"    : "orange",
    b"rgb32"    : "red",
    b"jpeg"     : "purple",
    b"png/P"    : "indigo",
    b"png/L"    : "teal",
    b"h265"     : "khaki",
    b"vp9"      : "lavender",
    b"mpeg4"    : "black",
    b"scroll"   : "brown",
    }

ALPHA = 0.3
#converted from gtk lookups:
BOX_COLORS = {
    b"h264"     : (0.0,                 0.0,                    0.9999847412109375, ALPHA),
    b"h265"     : (0.941162109375,      0.901947021484375,      0.54901123046875,   ALPHA),
    b"jpeg"     : (0.501953125,         0.0,                    0.501953125,        ALPHA),
    b"mpeg4"    : (0.0,                 0.0,                    0.0,                ALPHA),
    b"png"      : (0.9999847412109375,  0.9999847412109375,     0.0,                ALPHA),
    b"png/L"    : (0.0,                 0.501953125,            0.501953125,        ALPHA),
    b"png/P"    : (0.2941131591796875,  0.0,                    0.509796142578125,  ALPHA),
    b"rgb24"    : (0.9999847412109375,  0.6470489501953125,     0.0,                ALPHA),
    b"rgb32"    : (0.9999847412109375,  0.0,                    0.0,                ALPHA),
    b"scroll"   : (0.6470489501953125,  0.164703369140625,      0.164703369140625,  ALPHA),
    b"vp8"      : (0.0,                 0.501953125,            0.0,                ALPHA),
    b"vp9"      : (0.901947021484375,   0.901947021484375,      0.980377197265625,  ALPHA),
}

BLACK = 0, 0, 0, 0
def get_default_paint_box_color():
    return BLACK

def get_paint_box_color(encoding):
    return BOX_COLORS.get(encoding, BLACK)
