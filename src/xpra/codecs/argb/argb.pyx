# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True


cdef extern from "../buffers/buffers.h":
    int    object_as_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)
    int    object_as_write_buffer(object obj, const void ** buffer, Py_ssize_t * buffer_len)

cdef extern from "string.h":
    void * memcpy(void * destination, void * source, size_t num)

cdef extern from "stdlib.h":
    void free(void* mem)


import struct
from xpra.log import Logger
log = Logger("encoding")


def argb_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # buf is a Python buffer object
    cdef const unsigned char * cbuf = <unsigned char *> 0
    cdef Py_ssize_t cbuf_len = 0
    assert object_as_buffer(buf, <const void**> &cbuf, &cbuf_len)==0, "cannot convert %s to a readable buffer" % type(buf)
    return argbdata_to_rgba(cbuf, cbuf_len)

cdef argbdata_to_rgba(const unsigned char* argb, int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    rgba = bytearray(argb_len)
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
    assert object_as_buffer(buf, <const void**> &cbuf, &cbuf_len)==0, "cannot convert %s to a readable buffer" % type(buf)
    return argbdata_to_rgb(cbuf, cbuf_len)

cdef argbdata_to_rgb(const unsigned char *argb, int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    #number of pixels:
    cdef int mi = argb_len/4                #@DuplicateSignature
    #3 bytes per pixel:
    rgb = bytearray(mi*3)
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
    assert object_as_buffer(buf, <const void**> &bgra_buf, &bgra_buf_len)==0, "cannot convert %s to a readable buffer" % type(buf)
    return bgradata_to_rgb(bgra_buf, bgra_buf_len)

cdef bgradata_to_rgb(const unsigned char* bgra, int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len/4                #@DuplicateSignature
    #3 bytes per pixel:
    rgb = bytearray(mi*3)
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
    assert object_as_buffer(buf, <const void**> &bgra_buf2, &bgra_buf_len2)==0, "cannot convert %s to a readable buffer" % type(buf)
    return bgradata_to_rgba(bgra_buf2, bgra_buf_len2)

cdef bgradata_to_rgba(const unsigned char* bgra, int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #same number of bytes:
    rgba = bytearray(bgra_len)
    cdef int i = 0                      #@DuplicateSignature
    while i < bgra_len:
        rgba[i]   = bgra[i+2]           #R
        rgba[i+1] = bgra[i+1]           #G
        rgba[i+2] = bgra[i]             #B
        rgba[i+3] = bgra[i+3]           #A
        i += 4
    return rgba


def premultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0
    cdef Py_ssize_t cbuf_len = 0                #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert object_as_write_buffer(buf, <void **>&cbuf, &cbuf_len)==0
    do_premultiply_argb_in_place(cbuf, cbuf_len)

cdef do_premultiply_argb_in_place(unsigned int *buf, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b
    cdef unsigned int argb
    assert sizeof(int) == 4
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef int i
    for 0 <= i < argb_len / 4:
        argb = buf[i]
        a = (argb >> 24) & 0xff
        r = (argb >> 16) & 0xff
        r = r * a / 255
        g = (argb >> 8) & 0xff
        g = g * a / 255
        b = (argb >> 0) & 0xff
        b = b * a / 255
        buf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

def unpremultiply_argb_in_place(buf):
    # b is a Python buffer object
    cdef unsigned int * cbuf = <unsigned int *> 0   #@DuplicateSignature
    cdef Py_ssize_t cbuf_len = 0                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert object_as_write_buffer(buf, <void **>&cbuf, &cbuf_len)==0, "cannot convert %s to a writable buffer" % type(buf)
    do_unpremultiply_argb_in_place(cbuf, cbuf_len)

cdef do_unpremultiply_argb_in_place(unsigned int * buf, Py_ssize_t buf_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data, in-place.
    cdef unsigned int a, r, g, b                    #@DuplicateSignature
    cdef unsigned int argb                          #@DuplicateSignature
    assert sizeof(int) == 4
    assert buf_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % buf_len
    cdef int i                                      #@DuplicateSignature
    for 0 <= i < buf_len / 4:
        argb = buf[i]
        a = (argb >> 24) & 0xff
        if a==0:
            buf[i] = 0
            continue
        r = (argb >> 16) & 0xff
        r = r * 255 / a
        g = (argb >> 8) & 0xff
        g = g * 255 / a
        b = (argb >> 0) & 0xff
        b = b * 255 / a
        buf[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)

def unpremultiply_argb(buf):
    # b is a Python buffer object
    cdef unsigned int * argb = <unsigned int *> 0   #@DuplicateSignature
    cdef Py_ssize_t argb_len = 0                    #@DuplicateSignature
    assert sizeof(int) == 4
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    assert object_as_buffer(buf, <const void **>&argb, &argb_len)==0
    return do_unpremultiply_argb(argb, argb_len)


#precalculate indexes in native endianness:
tmp = str(struct.pack("=BBBB", 0, 1, 2, 3))
cdef int B = tmp.find('\0')
cdef int G = tmp.find('\1')
cdef int R = tmp.find('\2')
cdef int A = tmp.find('\3')

cdef do_unpremultiply_argb(unsigned int * argb_in, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data
    cdef unsigned int a, r, g, b                #@DuplicateSignature
    cdef unsigned int argb                      #@DuplicateSignature
    assert sizeof(int) == 4
    assert argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    argb_out = bytearray(argb_len)
    cdef int i                                  #@DuplicateSignature
    for 0 <= i < argb_len / 4:
        argb = argb_in[i]
        a = (argb >> 24) & 0xff
        r = (argb >> 16) & 0xff
        g = (argb >> 8) & 0xff
        b = (argb >> 0) & 0xff
        if a!=0:
            r = r * 255 / a
            g = g * 255 / a
            b = b * 255 / a
        else:
            r = 0
            g = 0
            b = 0
        #we could use struct pack to avoid endianness issues
        #but this is python 2.5 onwards only and is probably slower:
        #struct.pack_into("=BBBB", argb_out, i*4, b, g, r, a)
        argb_out[i*4+B] = b
        argb_out[i*4+G] = g
        argb_out[i*4+R] = r
        argb_out[i*4+A] = a
    return argb_out


cdef roundup(int n, int m):
    return (n + m - 1) & ~(m - 1)

def restride_image(image):
    #NOTE: this must be called from the UI thread!
    cdef int stride = image.get_rowstride()
    cdef int width = image.get_width()
    pixel_format = image.get_pixel_format()
    cdef int rstride = roundup(width*len(pixel_format), 4)   #a reasonable stride: rounded up to 4
    cdef int height = image.get_height()
    if stride<8 or rstride>stride or height<=2:
        return False                    #not worth it
    pixels = image.get_pixels()
    cdef unsigned char *img_buf
    cdef Py_ssize_t img_buf_len
    assert object_as_buffer(pixels, <const void**> &img_buf, &img_buf_len)==0, "cannot convert %s to a readable buffer" % type(pixels)
    if img_buf_len<=0:
        return False
    cdef int out_size = rstride*height                  #desirable size we could have
    #is it worth re-striding to save space:
    if img_buf_len-out_size<1024 or out_size*110/100>img_buf_len:
        return False
    #we'll save at least 1KB and 10%, do it
    #Note: we could also change the pixel format whilst we're at it
    # and convert BGRX to RGB for example (assuming RGB is also supported by the client)
    #this buffer is allocated by the imagewrapper, so it will be freed after use for us,
    #but we need to tell allocate_buffer not to free the current buffer (if there is one),
    #and we have to deal with this ourselves after we're done copying it
    cdef unsigned long ptr

    #save pixels pointer to free later:
    ptr = int(image.get_pixel_ptr())
    cdef unsigned long pixptr = ptr

    ptr = int(image.allocate_buffer(out_size, False))
    assert ptr>0, "allocate_buffer failed"
    cdef unsigned char *out = <unsigned char*> ptr

    cdef int ry = height
    for 0 <= ry < height:
        memcpy(out, img_buf, rstride)
        out += rstride
        img_buf += stride
    if pixptr:
        free(<void *> pixptr)
    log("restride_image: %s pixels re-stride saving %i%% from %s (%s bytes) to %s (%s bytes)" % (pixel_format, 100-100*out_size/img_buf_len, stride, img_buf_len, rstride, out_size))
    image.set_rowstride(rstride)
    return True
