# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef extern from "Python.h":
    ctypedef int Py_ssize_t
    int PyObject_AsWriteBuffer(object obj,
                               void ** buffer,
                               Py_ssize_t * buffer_len) except -1
    int PyObject_AsReadBuffer(object obj,
                              void ** buffer,
                              Py_ssize_t * buffer_len) except -1


#test for availability of bytearray
#in a way that does not cause Cython to fail to compile:
import __builtin__
_bytearray =  __builtin__.__dict__.get("bytearray")
if _bytearray is not None:
    def make_byte_buffer(len):
        return _bytearray(len)
else:
    #python 2.4 and older do not have bytearray, use array:
    import array
    def make_byte_buffer(len):              #@DuplicatedSignature
        return array.array('b', '\0' * len)


def argb_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef const unsigned char * cbuf = <unsigned char *> 0
    cdef Py_ssize_t cbuf_len = 0
    assert PyObject_AsReadBuffer(buf, <const void**> &cbuf, &cbuf_len)==0
    return argbdata_to_rgba(cbuf, cbuf_len)

cdef argbdata_to_rgba(const unsigned char* argb, int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    rgba = make_byte_buffer(argb_len)
    #number of pixels:
    cdef int i = 0
    while i < argb_len:
        rgba[i]    = argb[i+1]              #R
        rgba[i+1]  = argb[i+2]              #G
        rgba[i+2]  = argb[i+3]              #B
        rgba[i+3]  = argb[i]                #A
        i = i + 4
    return rgba

def argb_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef unsigned char * cbuf = <unsigned char *> 0     #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                        #@DuplicateSignature
    assert PyObject_AsReadBuffer(buf, <const void**> &cbuf, &cbuf_len)==0
    return argbdata_to_rgb(cbuf, cbuf_len)

cdef argbdata_to_rgb(const unsigned char *argb, int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    #number of pixels:
    cdef int mi = argb_len/4                #@DuplicateSignature
    #3 bytes per pixel:
    rgb = make_byte_buffer(mi*3)
    cdef int i = 0                          #@DuplicateSignature
    while i < argb_len:
        rgb[di]   = argb[i+1]               #R
        rgb[di+1] = argb[i+2]               #G
        rgb[di+2] = argb[i+3]               #B
        di += 3
        i += 4
    return rgb


def bgra_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef unsigned char * bgra_buf           #@DuplicateSignature
    cdef Py_ssize_t bgra_buf_len            #@DuplicateSignature
    assert PyObject_AsReadBuffer(buf, <const void**> &bgra_buf, &bgra_buf_len)==0
    return bgradata_to_rgb(bgra_buf, bgra_buf_len)

cdef bgradata_to_rgb(const unsigned char* bgra, int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len/4                #@DuplicateSignature
    #3 bytes per pixel:
    rgb = make_byte_buffer(mi*3)
    cdef int di = 0                         #@DuplicateSignature
    cdef int si = 0                         #@DuplicateSignature
    while si < bgra_len:
        rgb[di]   = bgra[si+2]              #R
        rgb[di+1] = bgra[si+1]              #G
        rgb[di+2] = bgra[si]                #B
        di += 3
        si += 4
    return rgb


def bgra_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef unsigned char * bgra_buf2
    cdef Py_ssize_t bgra_buf_len2
    assert PyObject_AsReadBuffer(buf, <const void**> &bgra_buf2, &bgra_buf_len2)==0
    return bgradata_to_rgba(bgra_buf2, bgra_buf_len2)

cdef bgradata_to_rgba(const unsigned char* bgra, int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #same number of bytes:
    rgba = make_byte_buffer(bgra_len)
    cdef int bi = 0                          #@DuplicateSignature
    while i < bgra_len:
        rgba[bi]   = bgra[bi+2]              #R
        rgba[bi+1] = bgra[bi+1]              #G
        rgba[bi+2] = bgra[bi]                #B
        rgba[bi+3] = bgra[bi+3]              #A
        i += 4
    return rgba


def premultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0
    cdef Py_ssize_t cbuf_len = 0                #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)==0
    do_premultiply_argb_in_place(cbuf, cbuf_len)

cdef do_premultiply_argb_in_place(unsigned int * cbuf, Py_ssize_t cbuf_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b
    assert sizeof(int) == 4
    assert cbuf_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % cbuf_len
    cdef int i
    for 0 <= i < cbuf_len / 4:
        a = (cbuf[i] >> 24) & 0xff
        r = (cbuf[i] >> 16) & 0xff
        r = r * a / 255
        g = (cbuf[i] >> 8) & 0xff
        g = g * a / 255
        b = (cbuf[i] >> 0) & 0xff
        b = b * a / 255
        cbuf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

def unpremultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0   #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert PyObject_AsWriteBuffer(buf, <void **>&cbuf, &cbuf_len)==0
    do_unpremultiply_argb_in_place(cbuf, cbuf_len)

cdef do_unpremultiply_argb_in_place(unsigned int * cbuf, Py_ssize_t cbuf_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert cbuf_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % cbuf_len
    cdef int i                                      #@DuplicateSignature
    for 0 <= i < cbuf_len / 4:
        a = (cbuf[i] >> 24) & 0xff
        if a==0:
            cbuf[i] = 0
            continue
        r = (cbuf[i] >> 16) & 0xff
        r = r * 255 / a
        g = (cbuf[i] >> 8) & 0xff
        g = g * 255 / a
        b = (cbuf[i] >> 0) & 0xff
        b = b * 255 / a
        cbuf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)
