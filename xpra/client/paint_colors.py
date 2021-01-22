#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017,2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


DEFAULT_BOX_COLORS = {
    "png"       : "yellow",
    "h264"      : "blue",
    "vp8"       : "green",
    "rgb24"     : "orange",
    "rgb32"     : "red",
    "webp"      : "pink",
    "jpeg"      : "purple",
    "png/P"     : "indigo",
    "png/L"     : "teal",
    "h265"      : "khaki",
    "vp9"       : "lavender",
    "mpeg4"     : "black",
    "scroll"    : "brown",
    "mpeg1"     : "olive",
    "mpeg2"     : "lime",
    }

ALPHA = 0.6
#converted from gtk lookups:
BOX_COLORS = {
    "h264"      : (0.0,                 0.0,                    0.9999847412109375, ALPHA),
    "h265"      : (0.941162109375,      0.901947021484375,      0.54901123046875,   ALPHA),
    "jpeg"      : (0.501953125,         0.0,                    0.501953125,        ALPHA),
    "mpeg4"     : (0.0,                 0.0,                    0.0,                ALPHA),
    "png"       : (0.9999847412109375,  0.9999847412109375,     0.0,                ALPHA),
    "png/L"     : (0.0,                 0.501953125,            0.501953125,        ALPHA),
    "png/P"     : (0.2941131591796875,  0.0,                    0.509796142578125,  ALPHA),
    "rgb24"     : (0.9999847412109375,  0.6470489501953125,     0.0,                ALPHA),
    "rgb32"     : (0.9999847412109375,  0.0,                    0.0,                ALPHA),
    "webp"      : (1.0,                 0.7529411764705882,     0.796078431372549,  ALPHA),
    "scroll"    : (0.6470489501953125,  0.164703369140625,      0.164703369140625,  ALPHA),
    "vp8"       : (0.0,                 0.501953125,            0.0,                ALPHA),
    "vp9"       : (0.901947021484375,   0.901947021484375,      0.980377197265625,  ALPHA),
    "mpeg1"     : (0.41796875,          0.5546875,              0.13671875,         ALPHA),
    "mpeg2"     : (0.75,                1.0,                    0,                  ALPHA),
}

BLACK = 0, 0, 0, 0
def get_default_paint_box_color():
    return BLACK

def get_paint_box_color(encoding):
    return BOX_COLORS.get(encoding, BLACK)
