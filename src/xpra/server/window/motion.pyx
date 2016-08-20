# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#!python
#cython: boundscheck=False, wraparound=False, cdivision=True

import time

cdef extern from "math.h":
    double log(double x)

from libc.stdint cimport int32_t, uint8_t, uint32_t

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

cdef extern from "../../buffers/crc32c.h":
    uint32_t crc32c(uint32_t crc, const void *buf, size_t len)


def CRC_Image(pixels, unsigned int width, unsigned int height, unsigned int rowstride, unsigned char bpp=4):
    cdef uint8_t *buf = NULL
    cdef Py_ssize_t buf_len = 0
    assert object_as_buffer(pixels, <const void**> &buf, &buf_len)==0
    assert buf_len>=rowstride*height, "buffer is too small for %ix%i" % (rowstride, height)
    crcs = []
    cdef unsigned int i
    cdef size_t row_len = width*bpp
    for i in range(height):
        crcs.append(crc32c(0, buf, row_len))
        buf += rowstride
    return crcs


def calculate_distances(array1, array2, int min_score=0, int max_distance=1000):
    #print("calculate_distances(..)")
    assert len(array1)==len(array2)
    cdef int l = len(array1)
    cdef int i, y1, y2, miny, maxy, d
    #we want fast array access,
    #so cache both arrays in C arrays:
    assert sizeof(int32_t)==32//8, "uint64_t is not 64-bit: %i!" % sizeof(int32_t)
    cdef size_t asize = l*(sizeof(int32_t))
    cdef int32_t *a1 = NULL
    cdef int32_t *a2 = NULL
    cdef int32_t *distances = NULL
    #print("calculate_distances(%s, %s, %i, %i)" % (array1, array2, elen, min_score))
    try:
        a1 = <int32_t*> xmemalign(asize)
        a2 = <int32_t*> xmemalign(asize)
        distances = <int32_t*> xmemalign(2*l*sizeof(int32_t))
        memset(<void*> distances, 0, 2*l*sizeof(int32_t))
        assert a1!=NULL and a2!=NULL and distances!=NULL
        for i in range(l):
            a1[i] = array1[i]
            a2[i] = array2[i]
        #now compare all the values
        for y1 in range(l):
            miny = max(0, y1-max_distance)
            maxy = min(l, y1+max_distance)
            for y2 in range(miny, maxy):
                if a1[y1]==a2[y2]:
                    d = y1-y2
                    distances[l+d] += 1
        r = {}
        for i in range(2*l):
            d = distances[i]
            if min_score<=0 or abs(d)>=min_score:
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
