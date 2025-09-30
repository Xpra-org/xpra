# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# this used to be implemented using a gtk.gdk.Rectangle
# but we don't want its union() behaviour which can be too expensive

#cython: boundscheck=False, wraparound=False, overflowcheck=False

cdef inline int MIN(int a, int b) noexcept nogil:   # pylint: disable=syntax-error
    if a<=b:
        return a
    return b

cdef inline int MAX(int a, int b) noexcept nogil:
    if a>=b:
        return a
    return b


cdef class rectangle:

    cdef readonly int x, y, width, height
    cdef readonly long hash

    def __init__(self, const int x, const int y, const int w, const int h):
        if w<0 or h<0:
            raise ValueError(f"invalid dimensions: {w}x{h}")
        self.x = x
        self.y = y
        self.width = w
        self.height = h
        self.hash = (self.x&0xffff)<<48+(self.y&0xffff)<<32+(self.width&0xffff)<<16+(self.height&0xffff)

    def __hash__(self):
        return self.hash

    def __str__(self):
        return "rectangle(%i, %i, %i, %i)" % (self.x, self.y, self.width, self.height)

    def __repr__(self):
        return "R(%i, %i, %i, %i)" % (self.x, self.y, self.width, self.height)

    def __richcmp__(self, object other, const int op):
        if not isinstance(other, rectangle):
            raise ValueError("cannot compare %s and %s" % (type(self), type(other)))
        cdef rectangle o = other
        if op==2:   #==
            return self.hash==o.hash and self.x==o.x and self.y==o.y and self.width==o.width and self.height==o.height
        elif op==3: #!=
            return self.x!=o.x or self.y!=o.y or self.width!=o.width or self.height!=o.height
        elif op==0: #<
            return self.x<o.x or self.y<o.y or self.width<o.width or self.height<o.height
        elif op==1: #<=
            return self.x<=o.x or self.y<=o.y or self.width<=o.width or self.height<=o.height
        elif op==4: #>
            return self.x>o.x or self.y>o.y or self.width>o.width or self.height>o.height
        elif op==5: #>=
            return self.x>=o.x or self.y>=o.y or self.width>=o.width or self.height>=o.height
        else:
            raise ValueError("invalid richcmp operator: %s" % op)

    def intersects(self, const int x, const int y, const int w, const int h) -> bool:
        cdef int  ix = MAX(self.x, x)
        cdef int  iw = MIN(self.x+self.width, x+w) - ix
        if iw<=0:
            return False
        cdef int  iy = MAX(self.y, y)
        cdef int  ih = MIN(self.y+self.height, y+h) - iy
        return ih>0

    def intersects_rect(self, rectangle rect) -> bool:
        return self.intersects(rect.x, rect.y, rect.width, rect.height)

    def intersection(self, const int x, const int y, const int w, const int h):
        """ returns the rectangle containing the intersection with the given area,
            or None
        """
        cdef int ix = MAX(self.x, x)
        cdef int iw = MIN(self.x+self.width, x+w) - ix
        if iw<=0:
            return None
        cdef int iy = MAX(self.y, y)
        cdef int ih = MIN(self.y+self.height, y+h) - iy
        if ih<=0:
            return None
        return rectangle(ix, iy, iw, ih)

    def intersection_rect(self, rectangle rect):
        return self.intersection(rect.x, rect.y, rect.width, rect.height)

    def contains(self, const int x, const int y, const int w, const int h) -> bool:
        return self.x<=x and self.y<=y and self.x+self.width>=x+w and self.y+self.height>=y+h

    def contains_rect(self, rectangle rect) -> bool:
        return self.contains(rect.x, rect.y, rect.width, rect.height)

    def subtract(self, const int x, const int y, const int w, const int h) -> list:
        """
        returns the rectangle(s) remaining when
        one subtracts the given rectangle from it
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
        cdef object rects = []
        #note: we do "width first", no redundant area
        #which means we prefer wider rectangles for the areas that would overlap (the corners)
        if self.y<y:
            #top:
            rects.append(rectangle(self.x, self.y, self.width, y-self.y))
        #height for both sides:
        cdef int sy = MAX(self.y, y)
        cdef int sh = MIN(self.y+self.height, y+h)-sy
        cdef int nsx, nsw
        if sh>0:
            if self.x<x:
                #left:
                nsx = self.x
                nsw = x-nsx
                rects.append(rectangle(nsx, sy, nsw, sh))
            if self.x+self.width>x+w:
                #right:
                nsx = x+w
                nsw = self.x+self.width-(x+w)
                rects.append(rectangle(nsx, sy, nsw, sh))
        if self.y+self.height>y+h:
            #bottom:
            rects.append(rectangle(self.x, y+h, self.width, self.y+self.height-(y+h)))
        return rects

    def subtract_rect(self, rectangle rect) -> list:
        return self.subtract(rect.x, rect.y, rect.width, rect.height)

    def get_geometry(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def clone(self):
        return rectangle(self.x, self.y, self.width, self.height)


def contains(object regions, const int x, const int y, const int w, const int h) -> bool:
    cdef int x2 = x+w
    cdef int y2 = y+h
    for r in regions:
        if x>=r.x and y>=r.y and x2<=(r.x+r.width) and y2<=(r.y+r.height):
            return True
    return False


def contains_rect(object regions, rectangle region) -> bool:
    return contains(regions, region.x, region.y, region.width, region.height)


def add_rectangle(object regions, rectangle region) -> int:
    #returns the number of pixels actually added
    cdef int x = region.x
    cdef int y = region.y
    cdef int w = region.width
    cdef int h = region.height
    cdef long total
    cdef rectangle r, sub
    for r in tuple(regions):
        #unroll contains() call:
        #if r.contains_rect(region):
        if r.x<=x and r.y<=y and r.x+r.width>=x+w and r.y+r.height>=y+h:
            #rectangle is contained in another rectangle,
            #so no need to add anything
            return 0
        if r.intersects(x, y, w, h):
            total = 0
            #only add the parts that are not already in the rectangle
            #it intersects:
            for sub in region.subtract_rect(r):
                total += add_rectangle(regions, sub)
            return total
    #not found at all, add it all:
    regions.append(region)
    return w*h


def remove_rectangle(object regions, rectangle region) -> None:
    copy = regions[:]
    cdef int x = region.x               #
    cdef int y = region.y               #
    cdef int w = region.width           #
    cdef int h = region.height          #
    cdef rectangle r
    new_regions = []
    for r in copy:
        new_regions += r.subtract(x, y, w, h)
    regions[:] = new_regions


def merge_all(rectangles) -> rectangle:
    if not rectangles:
        raise ValueError("no rectangles to merge")
    cdef rectangle r = rectangles[0]
    cdef int rx = r.x
    cdef int ry = r.y
    cdef int rx2 = r.x + r.width
    cdef int ry2 = r.y + r.height
    cdef int x2, y2
    for r in rectangles:
        if not r:
            continue
        if r.x<rx:
            rx = r.x
        if r.y<ry:
            ry = r.y
        x2 = r.x + r.width
        y2 = r.y + r.height
        if x2>rx2:
            rx2 = x2
        if y2>ry2:
            ry2 = y2
    return rectangle(rx, ry, rx2-rx, ry2-ry)
