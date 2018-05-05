# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import cairo

from xpra.log import Logger
log = Logger("paint")

from xpra.os_util import monotonic_time


def setup_cairo_context(context, ww, wh, w, h, offset_x=0, offset_y=0):
    if w!=ww or h!=wh:
        context.scale(float(ww)/w, float(wh)/h)
    if offset_x!=0 or offset_y!=0:
        context.translate(offset_x, offset_y)
    context.set_operator(cairo.OPERATOR_SOURCE)

def cairo_paint_pointer_overlay(context, x, y, size, start_time):
    elapsed = max(0, monotonic_time()-start_time)
    if elapsed>6:
        return
    alpha = max(0, (5.0-elapsed)/5.0)
    log("cairo_paint_pointer_overlay%s drawing pointer with cairo at with alpha=%s", (context, x, y, size, start_time), alpha)
    context.set_source_rgba(0, 0, 0, alpha)
    context.set_line_width(1)
    context.move_to(x-size, y)
    context.line_to(x+size, y)
    context.stroke()
    context.move_to(x, y-size)
    context.line_to(x, y+size)
    context.stroke()
