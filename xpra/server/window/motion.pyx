# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2016-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False

import struct

from xpra.util import envbool, repr_ellipsized, csv
from xpra.log import Logger
log = Logger("encoding", "scroll")

from xpra.buffers.membuf cimport memalign, buffer_context #pylint: disable=syntax-error
from xpra.buffers.xxh cimport xxh3
from xpra.rectangle import rectangle


cdef int DEBUG = envbool("XPRA_SCROLL_DEBUG", False)


from libc.stdint cimport uint8_t, int16_t, uint16_t, uint32_t, uint64_t, uintptr_t
from libc.stdlib cimport free, malloc
from libc.string cimport memset


MIN_LINE_COUNT = 2

def h(v):
    return hex(v)[2:].rstrip("L")

cdef inline uint64_t hashtoint64(s):
    return <uint64_t> struct.unpack(b"@L", s)[0]

cdef da(uint64_t *a, uint16_t l):
    return repr_ellipsized(csv(h(a[i]) for i in range(l)))

cdef dd(uint16_t *d, uint16_t l):
    return csv(h(d[i]) for i in range(l))


assert sizeof(uint64_t)==64//8, "uint64_t is not 64-bit: %i!" % sizeof(uint64_t)


cdef class ScrollData:

    cdef object __weakref__
    #for each distance, keep track of the hit count:
    cdef uint16_t *distances
    cdef uint64_t *a1        #checksums of reference picture
    cdef uint64_t *a2        #checksums of latest picture
    cdef uint8_t matched
    cdef int16_t x
    cdef int16_t y
    cdef uint16_t width
    cdef uint16_t height

    def __cinit__(self, int16_t x=0, int16_t y=0, uint16_t width=0, uint16_t height=0):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def __repr__(self):
        return "ScrollDistances(%ix%i)" % (self.width, self.height)

    #only used by the unit tests:
    def test_update(self, arr):
        if self.a1:
            free(self.a1)
            self.a1 = NULL
        if self.a2:
            self.a1 = self.a2
            self.a2 = NULL
        cdef uint16_t l = len(arr)
        cdef size_t asize = l*(sizeof(uint64_t))
        self.a2 = <uint64_t*> memalign(asize)
        assert self.a2!=NULL, "checksum memory allocation failed"
        for i,v in enumerate(arr):
            self.a2[i] = <uint64_t> abs(v)

    def update(self, pixels, int16_t x, int16_t y, uint16_t width, uint16_t height, uint32_t rowstride, uint8_t bpp=4):
        """
            Add a new image to compare with,
            checksum its rows into a2,
            and push existing values (if we had any) into a1.
        """
        if DEBUG:
            log("%s.update%s a1=%#x, a2=%#x, distances=%#x, current size: %ix%i", self, (repr_ellipsized(pixels), x, y, width, height, rowstride, bpp), <uintptr_t> self.a1, <uintptr_t> self.a2, <uintptr_t> self.distances, self.width, self.height)
        assert width>0 and height>0, "invalid dimensions: %ix%i" % (width, height)
        #scroll area can move within the window:
        self.x = x
        self.y = y
        #but cannot change size (checksums would not match):
        if height!=self.height or width!=self.width:
            if self.a1!=NULL or self.a2!=NULL or self.distances!=NULL:
                log("new image size: %ix%i (was %ix%i), clearing reference checksums", width, height, self.width, self.height)
                self.free()
            self.width = width
            self.height = height
        #this is a new picture, shift a2 into a1 if we have it:
        if self.a1:
            free(self.a1)
            self.a1 = NULL
        if self.a2:
            self.a1 = self.a2
            self.a2 = NULL
        cdef size_t row_len = width*bpp
        #allocate new checksum array:
        assert self.a2==NULL
        cdef size_t asize = height*(sizeof(uint64_t))
        self.a2 = <uint64_t*> memalign(asize)
        assert self.a2!=NULL, "checksum memory allocation failed"
        #checksum each line of the pixel array:
        cdef Py_ssize_t min_buf_len = rowstride*height
        cdef uint64_t *a2 = self.a2
        cdef uint16_t i
        cdef uint8_t *buf
        with buffer_context(pixels) as bc:
            buf = <uint8_t*> (<uintptr_t> int(bc))
            assert len(bc)>=min_buf_len, "buffer length=%i is too small for %ix%i with rowstride %i, should be %i" % (
                    len(bc), width, height, rowstride, min_buf_len)
            assert row_len<=rowstride, "invalid row length: %ix%i=%i but rowstride is %i" % (width, bpp, width*bpp, rowstride)
            with nogil:
                for i in range(height):
                    a2[i] = <uint64_t> xxh3(buf, row_len)
                    buf += rowstride


    def calculate(self, uint16_t max_distance=1000):
        """
            Find all the scroll distances
            that would move lines from a1 to a2.
            The same lines may be accounted for multiple times.
            The result is stored in the "distances" array.
        """
        if DEBUG:
            log("calculate(%i) a1=%#x, a2=%#x, distances=%#x", max_distance, <uintptr_t> self.a1, <uintptr_t> self.a2, <uintptr_t> self.distances)
        if self.a1==NULL or self.a2==NULL:
            return
        cdef uint64_t *a1 = self.a1
        cdef uint64_t *a2 = self.a2
        cdef uint16_t l = self.height
        cdef uint16_t y1, y2
        cdef uint16_t miny, maxy
        cdef uint64_t a2v
        if self.distances==NULL:
            self.distances = <uint16_t*> memalign(2*l*sizeof(uint16_t))
            assert self.distances!=NULL, "distance memory allocation failed"
        cdef uint32_t matches = 0
        with nogil:
            memset(self.distances, 0, 2*l*sizeof(uint16_t))
            for y2 in range(l):
                #miny = max(0, y2-max_distance):
                if y2>max_distance:
                    miny = y2-max_distance
                else:
                    miny = 0
                #maxy = min(l, y2+max_distance)
                if y2+max_distance<l:
                    maxy = y2+max_distance
                else:
                    maxy = l
                a2v = a2[y2]
                if a2v==0:
                    continue
                for y1 in range(miny, maxy):
                    if a1[y1]==a2v:
                        #distance = y1-y2
                        self.distances[l-(y1-y2)] += 1
                        matches += 1
        if DEBUG:
            log("ScrollDistance: height=%i, calculate:", l)
            log(" a1=%s", da(self.a1, l))
            log(" a2=%s", da(self.a2, l))
            log(" %i matches, distances=%s", matches, dd(self.distances, l*2))

    def get_scroll_values(self, uint16_t min_hits=2):
        """
            Return two dictionaries that describe how to go from a1 to a2.
            * scrolls dictionary contains scroll definitions
            * non-scrolls dictionary is everything else (that will need to be repainted)
        """
        DEF MAX_MATCHES = 20
        if self.a1==NULL or self.a2==NULL:
            return None
        cdef uint16_t m_arr[MAX_MATCHES]    #number of hits
        cdef int16_t s_arr[MAX_MATCHES]     #scroll distance
        cdef int16_t i
        cdef uint8_t j
        cdef int16_t low = 0                #the lowest match value
        cdef int16_t matches
        cdef uint16_t* distances = self.distances
        cdef uint16_t l = self.height
        cdef size_t asize = l*sizeof(uint8_t)
        #use a temporary buffer to track the lines we have already dealt with:
        cdef uint8_t *line_state = <uint8_t*> malloc(asize)
        assert line_state!=NULL, "state map memory allocation failed"
        #find the best values (highest match count):
        with nogil:
            memset(line_state, 0, asize)
            memset(m_arr, 0, MAX_MATCHES*sizeof(uint16_t))
            memset(s_arr, 0, MAX_MATCHES*sizeof(int16_t))
            for i in range(2*l):
                matches = distances[i]
                if matches>low and matches>min_hits:
                    #add this candidate match to the arrays:
                    #find the lowest score index and replace it:
                    for j in range(MAX_MATCHES):
                        if m_arr[j]==low:
                            break
                    m_arr[j] = matches
                    s_arr[j] = i-l
                    #find the new lowest value we have:
                    low = matches
                    for j in range(MAX_MATCHES):
                        if m_arr[j]<low:
                            low = m_arr[j]
                            if low==0:
                                break
        #first collect the list of distances:
        #(there can be more than one distance value for each match count):
        scroll_hits = {}
        for i in range(MAX_MATCHES):
            if m_arr[i]>min_hits:
                scroll_hits.setdefault(m_arr[i], []).append(s_arr[i])
        if DEBUG:
            log("scroll hits=%s", dict(reversed(sorted(scroll_hits.items()))))
        #return a dict with the scroll distance as key,
        #and the list of matching lines in a dictionary:
        # {line-start : count, ..}
        cdef uint16_t start = 0, count = 0
        try:
            scrolls = {}
            #starting with the highest matches
            for i in reversed(sorted(scroll_hits.keys())):
                v = scroll_hits[i]
                for scroll in v:
                    #find matching lines:
                    line_defs = self.match_distance(line_state, scroll, MIN_LINE_COUNT)
                    if line_defs:
                        scrolls[scroll] = line_defs
            #same for the unmatched lines:
            #all the lines in tmp which have not been set by match_distance()
            line_defs = {}
            for i in range(l):
                if line_state[i]==0:
                    if count==0:
                        start = i
                    count += 1
                elif count>0:
                    line_defs[start] = count
                    count = 0
            if count>0:
                line_defs[start] = count
        finally:
            free(line_state)
        return scrolls, line_defs

    cdef match_distance(self, uint8_t *line_state, int16_t distance, const uint8_t min_line_count):
        """
            find the lines that match the given scroll distance,
            return a dictionary with the starting line as key
            and the number of matching lines as value
        """
        cdef uint64_t *a1 = self.a1
        cdef uint64_t *a2 = self.a2
        cdef uint64_t v
        assert abs(distance)<=self.height, "invalid distance %i for size %i" % (distance, self.height)
        cdef uint16_t rstart = 0
        cdef uint16_t rend = self.height-distance
        if distance<0:
            rstart = -distance
            rend = self.height
        cdef uint16_t i1, i2, start = 0, count = 0
        line_defs = {}
        for i1 in range(rstart, rend):
            i2 = i1+distance
            v = a1[i1]
            #if DEBUG:
            #    log("%i: a1=%i / a2=%i", i, a1[i], a2[i2])
            if v==a2[i2] and v!=0:
                #if DEBUG:
                #    log("match at %i: %i", i, a1[i])
                if count==0:
                    if line_state[i2]:
                        #this line has been matched already,
                        #we don't need to start here
                        continue
                    start = i1
                count += 1
            elif count>0:
                #we had a match
                if count>min_line_count:
                    line_defs[start] = count
                count = 0
        if count>min_line_count:
            #last few lines ended as a match:
            line_defs[start] = count
        #clear the ones we have matched:
        for start, count in line_defs.items():
            for i1 in range(count):
                line_state[start+distance+i1] = 1
        #if DEBUG:
        #    log("match_distance(%i)=%s", distance, line_defs)
        return line_defs


    def invalidate(self, int16_t x, int16_t y, uint16_t w, uint16_t h):
        if self.a2==NULL:
            #nothing to invalidate!
            return
        #do they intersect?
        rect = rectangle(self.x, self.y, self.width, self.height)
        inter = rect.intersection(x, y, w, h)
        if not inter:
            return
        #remove any lines that have been updated
        #by zeroing out their checksums:
        assert inter.height<=self.height
        assert inter.y>=rect.y and inter.y+inter.height<=rect.y+rect.height
        #the array indexes are relative to rect.y:
        cdef int start_y = inter.y-rect.y
        cdef int i
        for i in range(start_y, start_y+inter.height):
            self.a2[i] = 0
        cdef uint16_t nonzero = 0
        for i in range(self.height):
            if self.a2[i]!=0:
                nonzero += 1
        log("invalidated %i lines checksums from intersection of scroll area %s and rectangle %s, remains %i", inter.height, rect, (x, y, w, h), nonzero)
        #if more than half has already been invalidated, drop it completely:
        if nonzero<=rect.height//2:
            log("invalidating whole scroll data as only %i of it remains valid", 100*nonzero//rect.height)
            self.free()


    def get_best_match(self):
        if self.a1==NULL or self.a2==NULL:
            return 0, 0
        cdef uint16_t max_hits = 0
        cdef int d = 0
        cdef unsigned int i
        cdef uint16_t r = 2*self.height
        for i in range(r):
            if self.distances[i]>max_hits:
                max_hits = self.distances[i]
                d = i-self.height
        return d, max_hits

    def __dealloc__(self):
        self.free()

    def free(self):
        cdef void* ptr = <void*> self.distances
        if ptr:
            self.distances = NULL
            free(ptr)
        ptr = <void*> self.a1
        if ptr:
            self.a1 = NULL
            free(ptr)
        ptr = <void*> self.a2
        if ptr:
            self.a2 = NULL
            free(ptr)
