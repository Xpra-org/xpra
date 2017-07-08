#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.gtk_common.gtk_util import color_parse

DEFAULT_BOX_COLORS = {
    "png"       : "yellow",
    "h264"      : "blue",
    "vp8"       : "green",
    "rgb24"     : "orange",
    "rgb32"     : "red",
    "jpeg"      : "purple",
    "png/P"     : "indigo",
    "png/L"     : "teal",
    "h265"      : "khaki",
    "vp9"       : "lavender",
    "mpeg4"     : "black",
    "scroll"    : "brown",
    }


def get_fcolor(encoding):
    color_name = os.environ.get("XPRA_BOX_COLOR_%s" % encoding.upper(), DEFAULT_BOX_COLORS.get(encoding))
    try:
        c = color_parse(color_name)
    except:
        c = color_parse("black")
    #try and hope this works:
    try:
        return c.red/65536.0, c.green/65536.0, c.blue/65536.0, 0.3
    except:
        pass
    try:
        #it seems that in some GDK versions, we get a return value
        #made of (boolean, GDK.Color), we only want the color..
        c = c[1]
    except:
        from xpra.log import Logger
        log = Logger("util")
        log.warn("failed to parse color %s", color_name)
        return 0, 0, 0
    return c.red/65536.0, c.green/65536.0, c.blue/65536.0, 0.3

def get_default_paint_box_color():
    return get_fcolor("black")

BOX_COLORS = None
def get_paint_box_colors():
    global BOX_COLORS
    if BOX_COLORS is None:
        BOX_COLORS = {}
        for x in DEFAULT_BOX_COLORS.keys():
            BOX_COLORS[x] = get_fcolor(x)
    return BOX_COLORS

def get_paint_box_color(encoding):
    colors = get_paint_box_colors()
    return colors.get(encoding) or get_default_paint_box_color()
