# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: boundscheck=False, wraparound=False, cdivision=True, language_level=3

from xpra.util import first_time
from xpra.buffers.membuf cimport getbuf, padbuf, MemBuf, buffer_context #pylint: disable=syntax-error

from libc.stdint cimport uintptr_t, uint32_t, uint16_t, uint8_t

import struct
from xpra.log import Logger
log = Logger("encoding")

assert sizeof(int) == 4


cdef inline unsigned char clamp(int v):
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
    cdef MemBuf output_buf = padbuf(rgb565_len*2, 2)
    cdef uint32_t *rgbx = <uint32_t*> output_buf.get_mem()
    cdef uint16_t v
    cdef unsigned int i = 0
    cdef unsigned int l = rgb565_len//2
    for i in range(l):
        v = rgb565[i]
        rgbx[i] = 0xff000000 | (((v & 0xF800) >> 8) + ((v & 0x07E0) << 5) + ((v & 0x001F) << 19))
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
    cdef MemBuf output_buf = padbuf(rgb565_len*3//2, 3)
    cdef uint8_t *rgb = <uint8_t*> output_buf.get_mem()
    cdef uint32_t v
    cdef unsigned int i = 0
    cdef unsigned int l = rgb565_len//2
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
    cdef unsigned char* rgba = <unsigned char*> output_buf.get_mem()
    cdef unsigned int y = 0
    cdef unsigned int i = 0
    cdef unsigned int v
    for y in range(h):
        i = y*dst_stride
        for x in range(w):
            v = r210[x]
            rgba[i+2] = (v&0x000003ff) >> 2
            rgba[i+1] = (v&0x000ffc00) >> 12
            rgba[i]   = (v&0x3ff00000) >> 22
            rgba[i+3] = (v>>30)*85
            i = i + 4
        r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
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
    cdef unsigned char* rgba = <unsigned char*> output_buf.get_mem()
    cdef unsigned int y = 0
    cdef unsigned int i = 0
    cdef unsigned int v
    for y in range(h):
        i = y*dst_stride
        for x in range(w):
            v = r210[x]
            rgba[i+2] = (v&0x000003ff) >> 2
            rgba[i+1] = (v&0x000ffc00) >> 12
            rgba[i]   = (v&0x3ff00000) >> 22
            rgba[i+3] = 0xff
            i = i + 4
        r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
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
    cdef unsigned int y = 0
    cdef unsigned int i = 0
    cdef unsigned int v
    for y in range(h):
        i = y*dst_stride
        for x in range(w):
            v = r210[x]
            rgba[i+2] = (v&0x000003ff) >> 2
            rgba[i+1] = (v&0x000ffc00) >> 12
            rgba[i]   = (v&0x3ff00000) >> 22
            i = i + 3
        r210 = <unsigned int*> ((<uintptr_t> r210) + src_stride)
    return memoryview(output_buf)


def argb_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* argb
    with buffer_context(buf) as bc:
        argb = <const unsigned char*> (<uintptr_t> int(bc))
        return argbdata_to_rgba(argb, len(bc))

cdef argbdata_to_rgba(const unsigned char* argb, const int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    cdef MemBuf output_buf = getbuf(argb_len)
    cdef unsigned char* rgba = <unsigned char*> output_buf.get_mem()
    #number of pixels:
    cdef int i = 0
    while i < argb_len:
        rgba[i]    = argb[i+1]              #R
        rgba[i+1]  = argb[i+2]              #G
        rgba[i+2]  = argb[i+3]              #B
        rgba[i+3]  = argb[i]                #A
        i = i + 4
    return memoryview(output_buf)

def argb_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* argb
    with buffer_context(buf) as bc:
        argb = <const unsigned char*> (<uintptr_t> int(bc))
        return argbdata_to_rgb(argb, len(bc))

cdef argbdata_to_rgb(const unsigned char *argb, const int argb_len):
    if argb_len <= 0:
        return None
    assert argb_len>0 and argb_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % argb_len
    #number of pixels:
    cdef unsigned int mi = argb_len//4                #@DuplicateSignature
    #3 bytes per pixel:
    cdef MemBuf output_buf = padbuf(mi*3, 3)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int i = 0, di = 0                          #@DuplicateSignature
    while i < argb_len:
        rgb[di]   = argb[i+1]               #R
        rgb[di+1] = argb[i+2]               #G
        rgb[di+2] = argb[i+3]               #B
        di += 3
        i += 4
    return memoryview(output_buf)


def bgra_to_rgb(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned char*> (<uintptr_t> int(bc))
        return bgradata_to_rgb(bgra, len(bc))

cdef bgradata_to_rgb(const unsigned char* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #number of pixels:
    cdef int mi = bgra_len//4                #@DuplicateSignature
    #3 bytes per pixel:
    cdef MemBuf output_buf = padbuf(mi*3, 3)
    cdef unsigned char* rgb = <unsigned char*> output_buf.get_mem()
    cdef int di = 0, si = 0                  #@DuplicateSignature
    while si < bgra_len:
        rgb[di]   = bgra[si+2]              #R
        rgb[di+1] = bgra[si+1]              #G
        rgb[di+2] = bgra[si]                #B
        di += 3
        si += 4
    return memoryview(output_buf)

def bgra_to_rgba(buf):
    assert len(buf) % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % len(buf)
    cdef const unsigned char* bgra
    with buffer_context(buf) as bc:
        bgra = <const unsigned char*> (<uintptr_t> int(bc))
        return bgradata_to_rgba(bgra, len(bc))

cdef bgradata_to_rgba(const unsigned char* bgra, const int bgra_len):
    if bgra_len <= 0:
        return None
    assert bgra_len>0 and bgra_len % 4 == 0, "invalid buffer size: %s is not a multiple of 4" % bgra_len
    #same number of bytes:
    cdef MemBuf output_buf = getbuf(bgra_len)
    cdef unsigned char* rgba = <unsigned char*> output_buf.get_mem()
    cdef int i = 0                      #@DuplicateSignature
    while i < bgra_len:
        rgba[i]   = bgra[i+2]           #R
        rgba[i+1] = bgra[i+1]           #G
        rgba[i+2] = bgra[i]             #B
        rgba[i+3] = bgra[i+3]           #A
        i += 4
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
        if supports_transparency and "RGBA" in rgb_formats:
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
        if supports_transparency and "RGBA" in rgb_formats:
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
    warning_key = "format-not-handled-%s" % pixel_format
    if first_time(warning_key):
        log.warn("Warning: no matching argb function,")
        log.warn(" cannot convert %s to one of: %s", pixel_format, rgb_formats)
    return False
