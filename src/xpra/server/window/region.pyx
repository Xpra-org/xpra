# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# this used to be implemented using a gtk.gdk.Rectangle
# but we don't want its union() behaviour which can be too expensive

#cython: boundscheck=False, wraparound=False, overflowcheck=False, cdivision=True, unraisable_tracebacks=True, always_allow_keywords=False


#what I want is a real macro!
cdef inline int MIN(int a, int b):
    if a<=b:
        return a
    return b
cdef inline int MAX(int a, int b):
    if a>=b:
        return a
    return b


cdef class rectangle:

    cdef readonly int x, y, width, height
    cdef readonly long hash

    def __init__(self, const int x, const int y, const int w, const int h):
        assert w>=0 and h>=0
        self.x = x
        self.y = y
        self.width = w
        self.height = h
        self.hash = (self.x+self.y)<<16 + (self.width + self.height)

    def __hash__(self):
        return self.hash

    def __str__(self):
        return "rectangle(%i, %i, %i, %i)" % (self.x, self.y, self.width, self.height)

    def __repr__(self):
        return "R(%i, %i, %i, %i)" % (self.x, self.y, self.width, self.height)

    def __richcmp__(self, object other, const int op):
        if type(other)!=rectangle:
            raise Exception("cannot compare rectangle and %s" % type(other))
        cdef rectangle o = other
        if op==2:
            return self.x==other.x and self.y==other.y and self.width==other.width and self.height==other.height
        elif op==3:
            return self.x!=other.x or self.y!=other.y or self.width!=other.width or self.height!=other.height
        elif op==0:
            return self.x<other.x or self.y<other.y or self.width<other.width or self.height<other.height
        elif op==1:
            return self.x<=other.x or self.y<=other.y or self.width<=other.width or self.height<=other.height
        elif op==4:
            return self.x>other.x or self.y>other.y or self.width>other.width or self.height>other.height
        elif op==5:
            return self.x>=other.x or self.y>=other.y or self.width>=other.width or self.height>=other.height
        else:
            raise Exception("invalid richcmp operator: %s" % op)

    def intersects(self, const int x, const int y, const int w, const int h):
        cdef int  ix = MAX(self.x, x)
        cdef int  iw = MIN(self.x+self.width, x+w) - ix
        if iw<=0:
            return False
        cdef int  iy = MAX(self.y, y)
        cdef int  ih = MIN(self.y+self.height, y+h) - iy
        return ih>0

    def intersects_rect(self, rectangle rect):
        return self.intersects(rect.x, rect.y, rect.width, rect.height)

    def intersection(self, const int x, const int y, const int w, const int h):
        """ returns the rectangle containing the intersection with the given area,
            or None
        """
        cdef int ix = MAX(self.x, x)
        cdef int iy = MAX(self.y, y)
        cdef int iw = MIN(self.x+self.width, x+w) - ix
        cdef int ih = MIN(self.y+self.height, y+h) - iy
        if iw<=0 or ih<=0:
            return None
        return rectangle(ix, iy, iw, ih)

    def intersection_rect(self, rectangle rect):
        return self.intersection(rect.x, rect.y, rect.width, rect.height)


    def contains(self, const int x, const int y, const int w, const int h):
        return self.x<=x and self.y<=y and self.x+self.width>=x+w and self.y+self.height>=y+h

    def contains_rect(self, rectangle rect):
        return self.contains(rect.x, rect.y, rect.width, rect.height)


    def substract(self, const int x, const int y, const int w, const int h):
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
        cdef object rects = []
        #note: we do "width first", no redudant area
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

    def substract_rect(self, rectangle rect):
        return self.substract(rect.x, rect.y, rect.width, rect.height)

    def get_geometry(self):
        return (self.x, self.y, self.width, self.height)

    def clone(self):
        return rectangle(self.x, self.y, self.width, self.height)


def contains(object regions, const int x, const int y, const int w, const int h):       #@DuplicatedSignature
    cdef int x2 = x+w
    cdef int y2 = y+h
    return any(True for r in regions if (x>=r.x and y>=r.y and x2<=(r.x+r.width) and y2<=(r.y+r.height)))


def contains_rect(object regions, rectangle region):            #@DuplicatedSignature
    return contains(regions, region.x, region.y, region.width, region.height)


def add_rectangle(object regions, rectangle region):
    cdef int x = region.x
    cdef int y = region.y
    cdef int w = region.width
    cdef int h = region.height
    cdef rectangle r
    for r in list(regions):
        #unroll contains() call:
        #if r.contains_rect(region):
        if r.x<=x and r.y<=y and r.x+r.width>=x+w and r.y+r.height>=y+h:
            return False
        if r.intersects(x, y, w, h):
            #only keep the parts
            #that do not intersect with the new region we add:
            regions.remove(r)
            regions += r.substract(x, y, w, h)
    regions.append(region)
    return True

def remove_rectangle(object regions, rectangle region):
    copy = regions[:]
    regions[:] = []
    cdef int x = region.x               #
    cdef int y = region.y               #
    cdef int w = region.width           #
    cdef int h = region.height          #
    cdef int l = len(copy)
    cdef rectangle r
    for r in copy:
        regions += r.substract(x, y, w, h)

def merge_all(rectangles):
    cdef rectangle r               #
    cdef int rx, ry, rx2, ry2, x2, y2
    assert len(rectangles)>0
    r = rectangles[0]
    rx = r.x
    ry = r.y
    rx2 = r.x + r.width
    ry2 = r.y + r.height
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
