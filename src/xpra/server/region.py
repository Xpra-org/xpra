# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# this used to be implemented using a gtk.gdk.Rectangle
# but we don't want its union() behaviour which can be too expensive


from xpra.util import AdHocStruct
class rectangle(AdHocStruct):
    def __init__(self, x, y, w, h):
        assert w>=0 and h>=0
        self.x = x
        self.y = y
        self.width = w
        self.height = h

    def __str__(self):
        return "rectangle[%i, %i, %i, %i]" % (self.x, self.y, self.width, self.height)

    def __repr__(self):
        return "R[%i, %i, %i, %i]" % (self.x, self.y, self.width, self.height)

    def __eq__(self, other):
        return self.x==other.x and self.y==other.y and self.width==other.width and self.height==other.height

    def merge(self, x, y, w, h):
        newx = min(self.x, x)
        newy = min(self.y, y)
        self.width = max(self.x+self.width, x+w)-newx
        self.height = max(self.y+self.height, y+h)-newy
        self.x = newx
        self.y = newy

    def merge_rect(self, rect):
        self.merge(rect.x, rect.y, rect.width, rect.height)

    def intersects(self, x, y, w, h):
        ix = max(self.x, x)
        iw = min(self.x+self.width, x+w) - ix
        if iw<=0:
            return False
        iy = max(self.y, y)
        ih = min(self.y+self.height, y+h) - iy
        return ih>0

    def intersects_rect(self, rect):
        return self.intersects(rect.x, rect.y, rect.width, rect.height)

    def intersection(self, x, y, w, h):
        """ returns the rectangle containing the intersection with the given area,
            or None
        """
        ix = max(self.x, x)
        iy = max(self.y, y)
        iw = min(self.x+self.width, x+w) - ix
        ih = min(self.y+self.height, y+h) - iy
        if iw<=0 or ih<=0:
            return None
        return rectangle(ix, iy, iw, ih)

    def intersection_rect(self, rect):
        return self.intersection(rect.x, rect.y, rect.width, rect.height)


    def contains(self, x, y, w, h):
        return self.x<=x and self.y<=y and self.x+self.width>=x+w and self.y+self.height>=y+h

    def contains_rect(self, rect):
        return self.contains(rect.x, rect.y, rect.width, rect.height)


    def substract(self, x, y, w, h):
        """ returns the rectangle(s) remaining when
            one substracts the given rectangle from it, or None if nothing remains
        """
        if w==0 or h==0 or self.width==0 or self.height==0:
            #no rectangle, no change:
            return [self]
        if self.x+self.width<=x or self.y+self.height<=y or x+w<=self.x or y+h<=self.y:
            #no intersection, no change:
            return [self]
        if x<=self.x and y<=self.y and x+w>=self.x+self.width and y+h>=self.y+self.height:
            #area contains this rectangle, so nothing remains:
            return []
        rects = []
        #note: we do "width first", no redudant area
        #which means we prefer wider rectangles for the areas that would overlap (the corners)
        if self.y<y:
            #top:
            rects.append(rectangle(self.x, self.y, self.width, y-self.y))
        #height for both sides:
        sy = max(self.y, y)
        sh = min(self.y+self.height, y+h)-sy
        if sh>0:
            if self.x<x:
                #left:
                lhsx = self.x
                lhsw = x-lhsx
                rects.append(rectangle(lhsx, sy, lhsw, sh))
            if self.x+self.width>x+w:
                #right:
                rhsx = x+w
                rhsw = self.x+self.width-(x+w)
                rects.append(rectangle(rhsx, sy, rhsw, sh))
        if self.y+self.height>y+h:
            #bottom:
            rects.append(rectangle(self.x, y+h, self.width, self.y+self.height-(y+h)))
        return rects

    def substract_rect(self, rect):
        return self.substract(rect.x, rect.y, rect.width, rect.height)


    def clone(self):
        return rectangle(self.x, self.y, self.width, self.height)


def contains(regions, x, y, w, h):
    x2 = x+w
    y2 = y+h
    for r in regions:
        if x>=r.x and y>=r.y and x2<=(r.x+r.width) and y2<=(r.y+r.height):
            return True
    return False

def contains_rect(regions, region):
    return contains(regions, region.x, region.y, region.width, region.height)

def add_rectangle(regions, region):
    if contains(regions, region.x, region.y, region.width, region.height):
        return False
    for r in list(regions):
        if r.intersects_rect(region):
            #only keep the parts
            #that do not intersect with the new region we add:
            regions.remove(r)
            regions += r.substract_rect(region)
    regions.append(region)
    return True

def remove_rectangle(regions, region):
    copy = regions[:]
    regions[:] = []
    for r in copy:
        regions += r.substract_rect(region)

def merge_all(rectangles):
    rx = min((r.x for r in rectangles))
    ry = min((r.y for r in rectangles))
    rw = min((r.x+r.width for r in rectangles))
    rh = min((r.y+r.height for r in rectangles))
    return rectangle(rx, ry, rw, rh)
