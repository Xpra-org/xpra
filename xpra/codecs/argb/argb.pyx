# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False

from xpra.util import first_time
from xpra.buffers.membuf cimport getbuf, MemBuf, buffer_context #pylint: disable=syntax-error

from libc.stdint cimport uintptr_t, uint32_t, uint16_t, uint8_t

import struct
from xpra.log import Logger
log = Logger("encoding")


cdef inline unsigned int round8up(unsigned int n) nogil:
    return (n + 7) & ~7

cdef inline unsigned char clamp(int v) nogil:
    if v>255:
        return 255
    return <unsigned char> v


def bgr565_to_rgbx(buf):
    assert len(buf) % 2 == 0, "invalid buffer size: %s is not a multiple of 2" % len(buf)
    cdef const uint16_t *rgb565
    with buffer_context(buf) as bc:
        rgb565 = <const uint16_t*> (<uintptr_t> int(bc))
        return bgr565data_to_rgbx(rgb565, len(bc))

cdef bgr565data_to_rgbx(const uint16_t* rgb565, const int rgb565_len):
    if rgb565_len <= 0:
        return None
    assert rgb565_len>0 and rgb565_len % 2 == 0, "invalid buffer size: %s is not a multiple of 2" % rgb565_len
    cdef MemBuf output_buf = getbuf(rgb565_len*2)
    cdef uint32_t *rgbx = <uint32_t*> output_buf.get_mem()
    cdef uint16_t v
    cdef unsigned int l = rgb565_len//2
    with nogil:
        for i in range(l):
            v = rgb565[i]
            rgbx[i] = (<uint32_t> 0xff000000) | (((v & 0xF800) >> 8) | ((v & 0x07E0) << 5) | ((v & 0x001F) << 19))
    return memoryview(output_buf)

def bgr565_to_rgb(buf):
    assert len(buf) % 2 == 0, "invalid buffer size: %s is not a multiple of 2" % len(buf)
    cdef const uint16_t* rgb565
    with buffer_context(buf) as bc:
        rgb565 = <const uint16_t*> (<uintptr_t> int(bc))
        return bgr565data_to_rgb(rgb565, len(bc))

cdef bgr565data_to_rgb(const uint16_t* rgb565, const int rgb565_len):
    if rgb565_len <= 0:
        return None
    assert rgb565_len>0 and rgb565_len % 2 == 0, "invalid buffer size: %s is not a multiple of 2" % rgb565_len
    cdef MemBuf output_buf = getbuf(rgb565_len*3//2)
    cdef uint8_t *rgb = <uint8_t*> output_buf.get_mem()
    cdef uint32_t v, i
    cdef unsigned int l = rgb565_len//2
    with nogil:
        for i in range(l):
            v = rgb565[i]
            rgb[0] = (v & 0xF800) >> 8
            rgb[1] = (v & 0x07E0) >> 3
            rgb[2] = (v & 0x001F) << 3
            rgb += 3
    return memoryview(output_buf)


def r210_to_rgba(buf,
                 const unsigned int w, const unsigned int h,
                 const unsigned int src_stride, const unsigned int dst_stride):
    assert w*4<=src_stride, "invalid source stride %i for width %i" % (src_stride, w)
    assert w*4<=dst_stride, "invalid destination stride %i for width %i" % (dst_stride, w)
    cdef unsigned int* r210
    with buffer_context(buf) as bc:
        assert len(bc)>=<Py_ssize_t>(h*src_stride), "source buffer is %i bytes, which is too small for %ix%i" % (len(bc), src_stride, h)
        r210 = <unsigned int*> (<uintptr_t> int(bc))
        return r210data_to_rgba(r210, w, h, src_stride, dst_stride)

cdef r210data_to_rgba(unsigned int* r210,
                      const unsigned int w, const unsigned int h,
                      const unsigned int src_stride, const unsigned int dst_stride):
    cdef MemBuf output_buf = getbuf(h*dst_stride)
    cdef unsigned int* rgba = <unsigned int*> output_buf.get_mem()
    cdef unsigned int v, x, y = 0
    with nogil:
        while y<h:
            for x in range(w):
                v = r210[x]
                rgba[x] = (v&0x3fc00000) >> 22 | (v&0x000ff000) >> 4 | (v&0x000003fc) << 14 | ((v>>30)*85)<<24
            r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
            rgba = <unsigned int*> ((<uintptr_t> rgba) + dst_stride)
            y += 1
    return memoryview(output_buf)


def r210_to_rgbx(buf,
                 const unsigned int w, const unsigned int h,
                 const unsigned int src_stride, const unsigned int dst_stride):
    assert buf, "no buffer"
    assert w*4<=src_stride, "invalid source stride %i for width %i" % (src_stride, w)
    assert w*4<=dst_stride, "invalid destination stride %i for width %i" % (dst_stride, w)
    cdef unsigned int* r210
    with buffer_context(buf) as bc:
        assert len(bc)>=<Py_ssize_t>(h*src_stride), "source buffer is %i bytes, which is too small for %ix%i" % (len(bc), src_stride, h)
        r210 = <unsigned int*> (<uintptr_t> int(bc))
        return r210data_to_rgbx(r210, w, h, src_stride, dst_stride)

cdef r210data_to_rgbx(unsigned int* r210,
                      const unsigned int w, const unsigned int h,
                      const unsigned int src_stride, const unsigned int dst_stride):
    cdef MemBuf output_buf = getbuf(h*dst_stride)
    cdef unsigned int* rgbx = <unsigned int*> output_buf.get_mem()
    cdef unsigned int v, x, y = 0
    with nogil:
        while y<h:
            for x in range(w):
                v = r210[x]
                rgbx[x] = (v&0x3fc00000) >> 22 | (v&0x000ff000) >> 4 | (v&0x000003fc) << 14 | <unsigned int> 0xff000000
            r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
            rgbx = <unsigned int*> ((<uintptr_t> rgbx) + dst_stride)
            y += 1
    return memoryview(output_buf)


def r210_to_rgb(buf,
                const unsigned int w, const unsigned int h,
                const unsigned int src_stride, const unsigned int dst_stride):
    assert buf, "no buffer"
    assert w*4<=src_stride, "invalid source stride %i for width %i" % (src_stride, w)
    assert w*3<=dst_stride, "invalid destination stride %i for width %i" % (dst_stride, w)
    cdef unsigned int* r210
    with buffer_context(buf) as bc:
        assert len(bc)>=<Py_ssize_t>(h*src_stride), "source buffer is %i bytes, which is too small for %ix%i" % (len(bc), src_stride, h)
        r210 = <unsigned int*> (<uintptr_t> int(bc))
        return r210data_to_rgb(r210, w, h, src_stride, dst_stride)

#white:  3fffffff
#red:    3ff00000
#green:     ffc00
#blue:        3ff
#black:         0
cdef r210data_to_rgb(unsigned int* r210,
                     const unsigned int w, const unsigned int h,
                     const unsigned int src_stride, const unsigned int dst_stride):
    cdef MemBuf output_buf = getbuf(h*dst_stride)
    cdef unsigned char* rgba = <unsigned char*> output_buf.get_mem()
    cdef unsigned int i, v, y = 0
    with nogil:
        while y<h:
            i = y*dst_stride
            for x in range(w):
                v = r210[x]
                rgba[i+2] = (v&0x000003ff) >> 2
                rgba[i+1] = (v&0x000ffc00) >> 12
                rgba[i]   = (v&0x3ff00000) >> 22
                i += 3
            r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
            y += 1
    return memoryview(output_buf)

def bgrx_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* bgrx
    with buffer_context(buf) as bc:
        bgrx = <const unsigned int*> (<uintptr_t> int(bc))
        return bgrxdata_to_rgb(bgrx, len(bc))

cdef bgrxdata_to_rgb(const unsigned int *bgrx, const int bgrx_len):
    if bgrx_len <= 0:
        return None
    assert bgrx_len>0 and bgrx_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgrx_len
    #number of pixels:
    cdef int mi = bgrx_len//4
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi*3)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int si = 0, di = 0
    cdef unsigned int p
    with nogil:
        while si < mi:
            p = bgrx[si]
            rgb[di]   = p & 0xFF                #R
            rgb[di+1] = (p>>8) & 0xFF           #G
            rgb[di+2] = (p>>16) & 0xFF          #B
            di += 3
            si += 1
    return memoryview(output_buf)


def bgrx_to_l(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* bgrx
    with buffer_context(buf) as bc:
        bgrx = <const unsigned int*> (<uintptr_t> int(bc))
        return bgrxdata_to_l(bgrx, len(bc))

cdef bgrxdata_to_l(const unsigned int *bgrx, const int bgrx_len):
    if bgrx_len <= 0:
        return None
    assert bgrx_len>0 and bgrx_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgrx_len
    #number of pixels:
    cdef int mi = bgrx_len//4
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi)
    cdef unsigned char* l = <unsigned char*> output_buf.get_mem()
    cdef int i = 0
    cdef unsigned int p
    cdef unsigned char r, g, b
    with nogil:
        while i < mi:
            p = bgrx[i]
            r = p & 0xFF                #R
            g = (p>>8) & 0xFF           #G
            b = (p>>16) & 0xFF          #B
            l[i] = (r*3+b+g*4)>>3
            i += 1
    return memoryview(output_buf)


def bgr_to_l(buf):
    assert len(buf) % 3 == 0, "invalid buffer size: %s is not a multiple of 3" % len(buf)
    cdef const unsigned char* bgr
    with buffer_context(buf) as bc:
        bgr = <const unsigned char*> (<uintptr_t> int(bc))
        return rgbdata_to_l(bgr, len(bc), 2, 1, 0)

def rgb_to_l(buf):
    assert len(buf) % 3 == 0, "invalid buffer size: %s is not a multiple of 3" % len(buf)
    cdef const unsigned char* bgr
    with buffer_context(buf) as bc:
        bgr = <const unsigned char*> (<uintptr_t> int(bc))
        return rgbdata_to_l(bgr, len(bc), 0, 1, 2)

cdef rgbdata_to_l(const unsigned char *bgr, const int bgr_len,
                  const unsigned char rindex, const unsigned char gindex, const unsigned char bindex):
    if bgr_len <= 0:
        return None
    assert bgr_len>0 and bgr_len % 3 == 0, "invalid buffer size: %s is not a multiple of 3" % bgr_len
    #number of pixels:
    cdef int mi = bgr_len//3
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi)
    cdef unsigned char* l = <unsigned char*> output_buf.get_mem()
    cdef int i = 0
    cdef unsigned char r, g, b
    with nogil:
        while i < mi:
            r = bgr[i+rindex]
            g = bgr[i+gindex]
            b = bgr[i+bindex]
            l[i] = (r*3+b+g*4)>>3
            i += 3
    return memoryview(output_buf)


def bgra_to_la(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned int*> (<uintptr_t> int(bc))
        return bgradata_to_la(bgra, len(bc))

cdef bgradata_to_la(const unsigned int *bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len//4
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi*2)
    cdef unsigned char* la = <unsigned char*> output_buf.get_mem()
    cdef int si = 0, di = 0
    cdef unsigned int p
    cdef unsigned char r, g, b, a
    with nogil:
        while si < mi:
            p = bgra[si]
            r = p & 0xFF
            g = (p>>8) & 0xFF
            b = (p>>16) & 0xFF
            a = (p>>24) & 0xFF
            la[di] = (r*3+b+g*4)>>3
            la[di+1] = a
            di += 2
            si += 1
    return memoryview(output_buf)


def argb_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* argb
    with buffer_context(buf) as bc:
        argb = <const unsigned int*> (<uintptr_t> int(bc))
        return argbdata_to_rgba(argb, len(bc))

cdef argbdata_to_rgba(const unsigned int* argb, const int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef int mi = argb_len//4
    cdef MemBuf output_buf = getbuf(argb_len)
    cdef unsigned int* rgba = <unsigned int*> output_buf.get_mem()
    cdef int i = 0
    cdef unsigned int p
    with nogil:
        while i < mi:
            p = argb[i]
            rgba[i] = p>>8 | (p&0xff)<<24
            i += 1
    return memoryview(output_buf)

def argb_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* argb
    with buffer_context(buf) as bc:
        argb = <const unsigned int*> (<uintptr_t> int(bc))
        return argbdata_to_rgb(argb, len(bc))

cdef argbdata_to_rgb(const unsigned int* argb, const int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    #number of pixels:
    cdef int mi = argb_len//4
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi*3)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int si = 0, di = 0
    cdef unsigned int p
    with nogil:
        while si < mi:
            p = argb[si]
            rgb[di]   = (p>>8)&0xFF             #R
            rgb[di+1] = (p>>16)&0xFF            #G
            rgb[di+2] = (p>>24)&0xFF            #B
            di += 3
            si += 1
    return memoryview(output_buf)


def bgra_to_rgb222(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned char*> (<uintptr_t> int(bc))
        return bgradata_to_rgb222(bgra, len(bc))

cdef bgradata_to_rgb222(const unsigned char* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len//4                #@DuplicateSignature
    #1 byte per pixel:
    cdef MemBuf output_buf = getbuf(mi)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int di = 0, si = 0                  #@DuplicateSignature
    with nogil:
        while si < bgra_len:
            rgb[di] = ((bgra[si+2]>>2) & 0x30) | ((bgra[si+1]>>4) & 0xC) | ((bgra[si]>>6) & 0x3)
            di += 1
            si += 4
    return memoryview(output_buf)


def bgra_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned int*> (<uintptr_t> int(bc))
        return bgradata_to_rgb(bgra, len(bc))

cdef bgradata_to_rgb(const unsigned int* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len//4
    #3 bytes per pixel:
    cdef MemBuf output_buf = getbuf(mi*3)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int di = 0, si = 0
    cdef unsigned int p
    with nogil:
        while si < mi:
            p = bgra[si]
            rgb[di]   = (p>>16) & 0xFF          #R
            rgb[di+1] = (p>>8) & 0xFF           #G
            rgb[di+2] = p & 0xFF                #B
            di += 3
            si += 1
    return memoryview(output_buf)

def bgra_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned int* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned int*> (<uintptr_t> int(bc))
        return bgradata_to_rgba(bgra, len(bc))

cdef bgradata_to_rgba(const unsigned int* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    cdef int mi = bgra_len//4
    cdef MemBuf output_buf = getbuf(bgra_len)
    cdef unsigned int* rgba = <unsigned int*> output_buf.get_mem()
    cdef int i = 0
    cdef unsigned int p
    with nogil:
        while i < mi:
            p = bgra[i]
            rgba[i] = (p>>16) & 0xff | p & 0xff00 | (p & 0xff)<<16 | p&(<unsigned int>0xff000000)
            i += 1
    return memoryview(output_buf)

def rgba_to_bgra(buf):
    #same: just a swap
    return bgra_to_rgba(buf)


def bgra_to_rgbx(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned char*> (<uintptr_t> int(bc))
        return bgradata_to_rgbx(bgra, len(bc))

cdef bgradata_to_rgbx(const unsigned char* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #same number of bytes:
    cdef MemBuf output_buf = getbuf(bgra_len)
    cdef unsigned char* rgbx = <unsigned char*> output_buf.get_mem()
    cdef int i = 0                      #@DuplicateSignature
    with nogil:
        while i < bgra_len:
            rgbx[i]   = bgra[i+2]           #R
            rgbx[i+1] = bgra[i+1]           #G
            rgbx[i+2] = bgra[i]             #B
            rgbx[i+3] = 0xff                #X
            i += 4
    return memoryview(output_buf)




def premultiply_argb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    # b is a Python buffer object
    cdef unsigned int *argb
    with buffer_context(buf) as bc:
        argb = <unsigned int*> (<uintptr_t> int(bc))
        return do_premultiply_argb(argb, len(bc))

cdef do_premultiply_argb(unsigned int *buf, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data
    cdef unsigned char a, r, g, b                #@DuplicateSignature
    cdef unsigned int argb                      #@DuplicateSignature
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef MemBuf output_buf = getbuf(argb_len)
    cdef unsigned int* argb_out = <unsigned int*> output_buf.get_mem()
    cdef int i                                  #@DuplicateSignature
    with nogil:
        for 0 <= i < argb_len / 4:
            argb = buf[i]
            a = (argb >> 24) & 0xff
            r = (argb >> 16) & 0xff
            r = r * a // 255
            g = (argb >> 8) & 0xff
            g = g * a // 255
            b = (argb >> 0) & 0xff
            b = b * a // 255
            argb_out[i] = (a << 24) | (r << 16) | (g << 8) | (b << 0)
    return memoryview(output_buf)


def unpremultiply_argb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef unsigned int *argb
    with buffer_context(buf) as bc:
        argb = <unsigned int*> (<uintptr_t> int(bc))
        return do_unpremultiply_argb(argb, len(bc))


#precalculate indexes in native endianness:
tmp = struct.pack(b"=L", 0 + 1*(2**8) + 2*(2**16) + 3*(2**24))
#little endian will give 0, 1, 2, 3
#big endian should give 3, 2, 1, 0 (untested)
cdef unsigned char B = tmp.index(b'\0')
cdef unsigned char G = tmp.index(b'\1')
cdef unsigned char R = tmp.index(b'\2')
cdef unsigned char A = tmp.index(b'\3')

cdef do_unpremultiply_argb(unsigned int * argb_in, Py_ssize_t argb_len):
    # cbuf contains non-premultiplied ARGB32 data in native-endian.
    # We convert to premultiplied ARGB32 data
    cdef unsigned char a, r, g, b                #@DuplicateSignature
    cdef unsigned int argb                      #@DuplicateSignature
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef MemBuf output_buf = getbuf(argb_len)
    cdef unsigned char* argb_out = <unsigned char*> output_buf.get_mem()
    cdef int i                                  #@DuplicateSignature
    with nogil:
        for 0 <= i < argb_len // 4:
            argb = argb_in[i]
            a = (argb >> 24) & 0xff
            r = (argb >> 16) & 0xff
            g = (argb >> 8) & 0xff
            b = (argb >> 0) & 0xff
            if a!=0:
                r = clamp(r * 255 // a)
                g = clamp(g * 255 // a)
                b = clamp(b * 255 // a)
            else:
                r = 0
                g = 0
                b = 0
            #we could use struct pack to avoid endianness issues
            #but this is python 2.5 onwards only and is probably slower:
            #struct.pack_into(b"=BBBB", argb_out, i*4, b, g, r, a)
            argb_out[i*4+B] = b
            argb_out[i*4+G] = g
            argb_out[i*4+R] = r
            argb_out[i*4+A] = a
    return memoryview(output_buf)


def alpha(image):
    pixel_format = image.get_pixel_format()
    cdef char i = pixel_format.find("A")
    if i<0 or i>=4:
        return None
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    assert len(pixels) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(pixels)
    cdef const unsigned char* rgba
    with buffer_context(pixels) as bc:
        rgba = <const unsigned char*> (<uintptr_t> int(bc))
        return alpha_data(rgba, len(bc), i)

cdef alpha_data(const unsigned char* rgba, const int rgba_len, const char index):
    if rgba_len <= 0:
        return None
    assert rgba_len>0 and rgba_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % rgba_len
    cdef MemBuf output_buf = getbuf(rgba_len//4)
    cdef unsigned char* alpha = <unsigned char*> output_buf.get_mem()
    cdef int di = 0, si = index
    cdef unsigned int p
    with nogil:
        while si < rgba_len:
            alpha[di] = rgba[si]
            si += 4
            di += 1
    return memoryview(output_buf)


def argb_swap(image, rgb_formats, supports_transparency=False):
    """ use the argb codec to do the RGB byte swapping """
    pixel_format = image.get_pixel_format()
    #try to fallback to argb module
    #if we have one of the target pixel formats:
    pixels = image.get_pixels()
    assert pixels, "failed to get pixels from %s" % image
    cdef unsigned int rs = image.get_rowstride()
    cdef unsigned int w
    cdef unsigned int h
    if pixel_format=="r210":
        assert rs%4==0, "invalid rowstride for r210 is not a multiple of 4"
        #r210 never contains any transparency at present
        #if supports_transparency and "RGBA" in rgb_formats:
        #    log("argb_swap: r210_to_rgba for %s on %s", pixel_format, type(pixels))
        #    image.set_pixels(r210_to_rgba(pixels))
        #    image.set_pixel_format("RGBA")
        #    return True
        w = image.get_width()
        h = image.get_height()
        if "RGB" in rgb_formats:
            log("argb_swap: r210_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(r210_to_rgb(pixels, w, h, rs, w*3))
            image.set_pixel_format("RGB")
            image.set_rowstride(w*3)
            return True
        if "RGBX" in rgb_formats:
            log("argb_swap: r210_to_rgbx for %s on %s", pixel_format, type(pixels))
            image.set_pixels(r210_to_rgbx(pixels, w, h, rs, w*4))
            image.set_pixel_format("RGBX")
            image.set_rowstride(w*4)
            return True
    elif pixel_format=="BGR565":
        assert rs%2==0, "invalid rowstride for BGR565 is not a multiple of 2"
        if "RGB" in rgb_formats:
            log("argb_swap: bgr565_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgr565_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//2)
            return True
        if "RGBX" in rgb_formats:
            log("argb_swap: bgr565_to_rgbx for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgr565_to_rgbx(pixels))
            image.set_pixel_format("RGBX")
            image.set_rowstride(rs*2)
            return True
    elif pixel_format in ("BGRX", "BGRA"):
        assert rs%4==0, "invalid rowstride for %s is not a multiple of 4"  % pixel_format
        if pixel_format=="BGRX" and "L" in rgb_formats:
            log("argb_swap: bgrx_to_l for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgrx_to_l(pixels))
            image.set_pixel_format("L")
            return True
        if pixel_format=="BGRA" and "LA" in rgb_formats:
            log("argb_swap: bgra_to_la for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_la(pixels))
            image.set_pixel_format("LA")
            return True
        if pixel_format=="BGRA" and supports_transparency and "RGBA" in rgb_formats:
            log("argb_swap: bgra_to_rgba for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            log("argb_swap: bgra_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
        if "RGBX" in rgb_formats:
            log("argb_swap: bgra_to_rgbx for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgra_to_rgbx(pixels))
            image.set_pixel_format("RGBX")
            return True
    elif pixel_format in ("XRGB", "ARGB"):
        assert rs%4==0, "invalid rowstride for %s is not a multiple of 4"  % pixel_format
        if pixel_format=="ARGB" and supports_transparency and "RGBA" in rgb_formats:
            log("argb_swap: argb_to_rgba for %s on %s", pixel_format, type(pixels))
            image.set_pixels(argb_to_rgba(pixels))
            image.set_pixel_format("RGBA")
            return True
        if "RGB" in rgb_formats:
            log("argb_swap: argb_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(argb_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
    elif pixel_format in ("RGBA", "RGBX"):
        assert rs%4==0, "invalid rowstride for %s is not a multiple of 4"  % pixel_format
        if "RGB" in rgb_formats:
            log("argb_swap: bgrx_to_rgb for %s on %s", pixel_format, type(pixels))
            image.set_pixels(bgrx_to_rgb(pixels))
            image.set_pixel_format("RGB")
            image.set_rowstride(rs*3//4)
            return True
    warning_key = "format-not-handled-%s" % pixel_format
    if first_time(warning_key):
        log.warn("Warning: no matching argb function,")
        log.warn(" cannot convert %s to one of: %s", pixel_format, rgb_formats)
    return False


def bit_to_rectangles(buf, unsigned int w, unsigned int h):
    cdef const unsigned char* bits
    with buffer_context(buf) as bc:
        bits = <const unsigned char*> (<uintptr_t> int(bc))
        return bitdata_to_rectangles(bits, len(bc), w, h)

cdef bitdata_to_rectangles(const unsigned char* bitdata, const int bitdata_len, const unsigned int w, const unsigned int h):
    rectangles = []
    cdef unsigned int rowstride = round8up(w)//8
    cdef unsigned char b
    cdef unsigned int start, end, x, y
    for y in range(h):
        x = 0
        b = 0
        while x<w:
            #find the first black pixel,
            if b==0:
                #if there are no left-overs in b then
                #we can move 8 pixels at a time (1 byte):
                while x<w and bitdata[y*rowstride+x//8]==0:
                    x += 8
                if x>=w:
                    break
                #there is a black pixel in this byte (8 pixels):
                b = bitdata[y*rowstride+x//8]
                assert b!=0
            while (b & (1<<(7-x%8)))==0:
                x += 1
            if x>=w:
                break
            start = x
            end = 0
            x += 1
            #find the next white pixel,
            #first, continue searching in the current byte:
            while (x%8)>0:
                if (b & (1<<(7-x%8)))==0:
                    end = x
                    break
                b &= ~(1<<(7-x%8))
                x += 1
            if x>=w:
                end = x = w
            if end==0:
                #now we can move 8 pixels at a time (1 byte):
                while x<w and bitdata[y*rowstride+x//8]==0xff:
                    x += 8
                if x>=w:
                    end = x = w
                else:
                    #there is a white pixel in this byte (8 pixels):
                    b = bitdata[y*rowstride+x//8]
                    while b & (1<<(7-x%8)):
                        #clear this bit so we can continue looking for black pixels in b
                        #when we re-enter the loop at the top
                        b &= ~(1<<(7-x%8))
                        x += 1
                    if x>w:
                        x = w
                    end = x
                    if b==0:
                        x = round8up(x)
            if start<end:
                rectangles.append((start, y, end-start, 1))
    return rectangles
