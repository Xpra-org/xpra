# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# this used to be implemented using a gtk.gdk.Rectangle
# but we don't want its union() behaviour which can be too expensive


from xpra.util import AdHocStruct
class rectangle(AdHocStruct):
    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.width = w
        self.height = h

    def __eq__(self, other):
        return self.x==other.x and self.y==other.y and self.width==other.width and self.height==other.height

def _contains(regions, x, y, w, h):
    x2 = x+w
    y2 = y+h
    for r in regions:
        if x>=r.x and y>=r.y and x2<=(r.x+r.width) and y2<=(r.y+r.height):
            return True
    return False

def add_rectangle(regions, x, y, w, h):
    if not _contains(regions, x, y, w, h):
        regions.append(rectangle(x, y, w, h))
