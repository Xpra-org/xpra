# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, cdivision=True

import os
import time

from xpra.util import envbool
from xpra.log import Logger
logger = Logger("encoding")

import zlib
hashfn = None
if envbool("XPRA_XXHASH", True):
    try:
        import xxhash
        def hashfn(x):
            return xxhash.xxh64(x).intdigest()
    except ImportError as e:
        logger.warn("Warning: xxhash python bindings not found")
else:
    logger.warn("Warning: xxhash disabled")
if hashfn is None:
    logger.warn(" no scrolling detection")


cdef extern from "math.h":
    double log(double x)

from libc.stdint cimport int32_t, uint8_t, uint32_t, int64_t

cdef extern from "stdlib.h":
    int abs(int number)

cdef extern from "string.h":
    void free(void * ptr) nogil
    void *memset(void * ptr, int value, size_t num) nogil
    int memcmp(const void *a1, const void *a2, size_t size)

cdef extern from "../../buffers/memalign.h":
    void *xmemalign(size_t size) nogil

cdef extern from "../../buffers/buffers.h":
    int object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)


def CRC_Image(pixels, unsigned int width, unsigned int height, unsigned int rowstride, unsigned char bpp=4):
    global hashfn
    if not hashfn:
        return None
    cdef uint8_t *buf = NULL
    cdef Py_ssize_t buf_len = 0
    assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0
    assert buf_len>=0 and (<unsigned int> buf_len)>=rowstride*height, "buffer length %i is too small for %ix%i" % (buf_len, rowstride, height)
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

def calculate_distances(array1, array2, int min_score=0, int max_distance=1000):
    #print("calculate_distances(..)")
    assert len(array1)==len(array2)
    cdef int l = len(array1)
    cdef int i, y1, y2, miny, maxy, d
    #we want fast array access,
    #so cache both arrays in C arrays:
    assert sizeof(int64_t)==64//8, "uint64_t is not 64-bit: %i!" % sizeof(int64_t)
    cdef size_t asize = l*(sizeof(int64_t))
    cdef int64_t *a1 = NULL
    cdef int64_t *a2 = NULL
    cdef int64_t a2v = 0
    cdef int32_t *distances = NULL
    #print("calculate_distances(%s, %s, %i, %i)" % (array1, array2, elen, min_score))
    try:
        a1 = <int64_t*> xmemalign(asize)
        a2 = <int64_t*> xmemalign(asize)
        assert a1!=NULL and a2!=NULL, "failed to allocate %i bytes of scroll array memory" % asize
        for i in range(l):
            a1[i] = castint64(array1[i])
            a2[i] = castint64(array2[i])
        #now compare all the values
        distances = <int32_t*> xmemalign(2*l*sizeof(int32_t))
        assert distances!=NULL
        with nogil:
            memset(<void*> distances, 0, 2*l*sizeof(int32_t))
            for y2 in range(l):
                miny = max(0, y2-max_distance)
                maxy = min(l, y2+max_distance)
                a2v = a2[y2]
                if a2v==0:
                    continue
                for y1 in range(miny, maxy):
                    if a1[y1]==a2v:
                        #distance = y1-y2
                        distances[l+y1-y2] += 1
        r = {}
        for i in range(2*l):
            d = distances[i]
            if abs(d)>=min_score:
                r[i-l] = d
        return r
    finally:
        if a1!=NULL:
            free(a1)
        if a2!=NULL:
            free(a2)
        if distances!=NULL:
            free(distances)

def match_distance(array1, array2, int distance):
    assert len(array1)==len(array2)
    l = len(array1)
    if distance>=0:
        return [i for i,v in enumerate(array1) if (i+distance)<l and array2[i+distance]==v]
    distance = abs(distance)
    return [i+distance for i,v in enumerate(array2) if (i+distance)<l and array1[i+distance]==v]

def consecutive_lines(line_numbers):
    #print("line_numbers_to_rectangles(%s)" % (line_numbers, ))
    #aggregates consecutive lines:
    #[1,2,3,4,8,9] -> [(1,3), (8,1)]
    assert len(line_numbers)>0
    if len(line_numbers)==1:
        return [(line_numbers[0], 1)]
    cdef int start = line_numbers[0]
    cdef int last = start
    cdef int line = 0
    r = []
    for line in line_numbers[1:]:
        if line!=last+1:
            #new rectangle
            r.append((start, last-start+1))
            start = line
        last = line
    if last!=line_numbers[0]:
        r.append((start, last-start+1))
    return r
