# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2016-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, cdivision=True

import os
import time
import collections

from xpra.util import envbool
from xpra.log import Logger
log = Logger("encoding", "scroll")

from xpra.buffers.membuf cimport memalign, object_as_buffer

cdef int DEBUG = envbool("XPRA_SCROLL_DEBUG", False)
hashfn = None
if envbool("XPRA_XXHASH", True):
    try:
        import xxhash
        def hashfn(x):
            return xxhash.xxh64(x).intdigest()
    except ImportError as e:
        log.warn("Warning: xxhash python bindings not found")
else:
    log.warn("Warning: xxhash disabled")
if hashfn is None:
    log.warn(" no scrolling detection")


from libc.stdint cimport int32_t, uint8_t, uint16_t, int16_t, uint32_t, int64_t

cdef extern from "string.h":
    void free(void * ptr) nogil
    void *memset(void * ptr, int value, size_t num) nogil


def CRC_Image(pixels, unsigned int width, unsigned int height, unsigned int rowstride, unsigned char bpp=4):
    global hashfn
    if not hashfn:
        return None
    cdef uint8_t *buf = NULL
    cdef Py_ssize_t buf_len = 0
    assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0
    assert buf_len>=0 and (<unsigned int> buf_len)>=rowstride*height, "buffer is too small for %ix%i" % (rowstride, height)
    cdef unsigned int i
    cdef size_t row_len = width*bpp
    f = hashfn
    crcs = []
    for i in range(height):
        crcs.append(f(buf[:row_len]))
        buf += rowstride
    return crcs


DEF MAXINT64 = 2**63
DEF MAXUINT64 = 2**64
DEF MASK64 = 2**64-1
cdef inline castint64(v):
    if v>=MAXINT64:
        return v-MAXUINT64
    #assert v>=0, "invalid int to cast: %s" % v
    return v

cdef inline da(int64_t *a, uint16_t l):
    return [a[i] for i in range(l)]

cdef inline dd(uint16_t *d, uint16_t l):
    return [d[i] for i in range(l)]

cdef inline ds(int16_t *d, uint16_t l):
    return [d[i] for i in range(l)]


assert sizeof(int64_t)==64//8, "uint64_t is not 64-bit: %i!" % sizeof(int64_t)


cdef class ScrollDistances:

    cdef object __weakref__
    #for each distance, keep track of the hit count:
    cdef uint16_t* distances
    cdef uint16_t l
    cdef int64_t *a1
    cdef int64_t *a2

    def init(self, array1, array2, uint16_t max_distance=1000):
        assert len(array1)==len(array2)
        assert len(array1)<2**15 and len(array1)>0, "invalid array length: %i" % len(array1)
        self.l = len(array1)
        self.distances = <uint16_t*> memalign(2*self.l*sizeof(uint16_t))
        cdef size_t asize = self.l*(sizeof(int64_t))
        self.a1 = <int64_t*> memalign(asize)
        self.a2 = <int64_t*> memalign(asize)
        assert self.distances!=NULL and self.a1!=NULL and self.a2!=NULL, "scroll memory allocation failed"
        for i in range(self.l):
            self.a1[i] = castint64(array1[i])
            self.a2[i] = castint64(array2[i])
        #now compare all the values
        self.calculate(max_distance)

    def __repr__(self):
        return "ScrollDistances(%i)" % self.l

    cdef calculate(self, uint16_t max_distance=1000):
        cdef int64_t *a1 = self.a1
        cdef int64_t *a2 = self.a2
        cdef uint16_t l = self.l
        cdef uint16_t y1, y2
        cdef uint16_t miny=0, maxy=0
        cdef int64_t a2v
        with nogil:
            memset(self.distances, 0, 2*self.l*sizeof(uint16_t))
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
        if DEBUG:
            log("ScrollDistance: l=%i, calculate(%s, %s, %i)=%s", self.l, da(self.a1, self.l), da(self.a2, self.l), max_distance, dd(self.distances, self.l*2))

    def get_best_scroll_values(self, uint16_t min_hits=2):
        DEF MAX_MATCHES = 20
        cdef uint16_t m_arr[MAX_MATCHES]    #number of hits
        cdef int16_t s_arr[MAX_MATCHES]     #scroll distance
        cdef int16_t i
        cdef uint8_t j
        memset(m_arr, 0, MAX_MATCHES*sizeof(uint16_t))
        memset(s_arr, 0, MAX_MATCHES*sizeof(int16_t))
        cdef int16_t low = 0
        cdef int16_t matches
        cdef uint16_t* distances = self.distances
        cdef uint16_t l = self.l
        with nogil:
            for i in range(2*l):
                matches = distances[i]
                if matches>low and matches>min_hits:
                    #add this candidate match to the arrays:
                    for j in range(MAX_MATCHES):
                        if m_arr[j]==low:
                            break
                    m_arr[j] = matches
                    s_arr[j] = i-l
                    #find the new lowest value:
                    low = matches
                    for j in range(MAX_MATCHES):
                        if m_arr[j]<low:
                            low = m_arr[j]
                            if low==0:
                                break
        if DEBUG:
            log("get_best_scroll_values: arrays: matches=%s, scroll=%s", dd(m_arr, MAX_MATCHES), ds(s_arr, MAX_MATCHES))
        #first collect the list of distances sorted by highest number of matches:
        #(there can be more than one distance value for each match count):
        scroll_hits = {}
        for i in range(MAX_MATCHES):
            if m_arr[i]>min_hits:
                scroll_hits.setdefault(m_arr[i], []).append(s_arr[i])
        if DEBUG:
            log("scroll hits=%s", scroll_hits)
        #return a dict with the scroll distance as key,
        #and the list of matching lines in a dictionary:
        # {line-start : count, ..}
        #this is destructive as we clear the checksums after use in match_distance()
        scrolls = collections.OrderedDict()
        cdef uint16_t m
        #starting with the highest matches
        for m in reversed(sorted(scroll_hits.keys())):
            v = scroll_hits[m]
            for scroll in v:
                #find matching lines:
                line_defs = self.match_distance(scroll)
                if line_defs:
                    scrolls[scroll] = line_defs
        return scrolls

    def get_remaining_areas(self):
        #all the lines which have not been zeroed out
        #when we matched them in match_distance
        cdef int64_t *a2 = self.a2
        cdef uint16_t i, start = 0, count = 0
        line_defs = collections.OrderedDict()
        for i in range(self.l):
            if a2[i]!=0:
                if count==0:
                    start = i
                count += 1
            elif count>0:
                line_defs[start] = count
                count = 0
        if count>0:
            line_defs[start] = count
        return line_defs

    def match_distance(self, int16_t distance):
        """ find the lines that match the given scroll distance """
        cdef int64_t *a1 = self.a1
        cdef int64_t *a2 = self.a2
        cdef char swap = 0
        if distance<0:
            #swap order:
            swap = 1
            a1 = self.a2
            a2 = self.a1
            distance = -distance
        if DEBUG:
            log("match_distance(%i) l=%i, a1=%s, a2=%s", distance, self.l, da(a1, self.l), da(a2, self.l))
        assert distance<self.l, "invalid distance %i for size %i" % (distance, self.l)
        cdef uint16_t i, start = 0, count = 0
        line_defs = collections.OrderedDict()
        for i in range(self.l-distance):
            #if DEBUG:
            #    log("%i: a1=%i / a2=%i", i, a1[i], a2[i+distance])
            if a1[i]!=0 and a1[i]==a2[i+distance]:
                #if DEBUG:
                #    log("match at %i: %i", i, a1[i])
                if count==0:
                    #first match
                    if swap:
                        start = i+distance
                    else:
                        start = i
                count += 1
                #mark the target line as dealt with:
                if swap:
                    a1[i] = 0
                else:
                    a2[i+distance] = 0
            elif count>0:
                #we had a match
                line_defs[start] = count
                count = 0
        if count>0:
            #last few lines ended as a match:
            line_defs[start] = count
        if DEBUG:
            log("match_distance(%i)=%s", distance, line_defs)
        return line_defs


    def get_best_match(self):
        cdef int16_t max = 0
        cdef int d = 0
        cdef unsigned int i
        for i in range(2*self.l):
            if self.distances[i]>max:
                max = self.distances[i]
                d = i-self.l
        return d, max

    def __dealloc__(self):
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
        

def scroll_distances(array1, array2, unsigned int min_score=0, uint16_t max_distance=1000):
    cdef ScrollDistances sd = ScrollDistances()
    sd.init(array1, array2, max_distance)
    return sd
