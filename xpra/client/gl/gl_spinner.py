# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import math
from OpenGL.GL import (
    glBegin, glEnd,
    glVertex2i, glColor4f,
    GL_POLYGON,
    )

from xpra.os_util import monotonic_time
from xpra.client.spinner import cv


def draw_spinner(bw, bh):
    dim = min(bw/3.0, bh/3.0)
    t = monotonic_time()
    count = int(t*4.0)
    bx = bw//2
    by = bh//2
    for i in range(8):      #8 lines
        c = cv.trs[count%8][i]
        mi1 = math.pi*i/4-math.pi/16
        mi2 = math.pi*i/4+math.pi/16
        si1 = math.sin(mi1)
        si2 = math.sin(mi2)
        ci1 = math.cos(mi1)
        ci2 = math.cos(mi2)
        glBegin(GL_POLYGON)
        glColor4f(c, c, c, 1)
        glVertex2i(int(bx+si1*10), int(by+ci1*10))
        glVertex2i(int(bx+si1*dim), int(by+ci1*dim))
        glVertex2i(int(bx+si2*dim), int(by+ci2*dim))
        glVertex2i(int(bx+si2*10), int(by+ci2*10))
        glEnd()
