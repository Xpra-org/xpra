# This file is part of Xpra.
# Copyright (C) 2014-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# What is this workaround you ask?
# Well, pycairo can't handle raw pixel data in RGB format,
# and that's despite the documentation saying otherwise:
# http://cairographics.org/pythoncairopil/
# Because of this glaring omission, we would have to roundtrip via PNG.
# This workaround populates an image surface with RGB pixels using Cython.
# (not the most efficient implementation, but still 10 times faster than the alternative)
#
#"cairo.ImageSurface.create_for_data" is not implemented in GTK3!
# http://cairographics.org/documentation/pycairo/3/reference/surfaces.html#cairo.ImageSurface.create_for_data
# "Not yet available in Python 3"
#
#It is available in the cffi cairo bindings, which can be used instead of pycairo
# but then we can't use it from the draw callbacks:
# https://mail.gnome.org/archives/python-hackers-list/2011-December/msg00004.html
# "PyGObject just lacks the glue code that allows it to pass the statically-wrapped
# cairo.Pattern to introspected methods"


#cython: boundscheck=False

from typing import Dict
from collections.abc import Sequence

from cairo import ImageSurface

from libc.stdint cimport uintptr_t
from libc.string cimport memcpy
from xpra.buffers.membuf cimport buffer_context


cdef extern from "Python.h":
    ctypedef struct PyObject:
        pass
    void * PyCapsule_Import(const char *name, int no_block)

cdef extern from "cairo/cairo.h":
    ctypedef struct cairo_surface_t:
        pass

    #typedef enum _cairo_format {
    ctypedef enum cairo_format_t:
        CAIRO_FORMAT_INVALID
        CAIRO_FORMAT_ARGB32
        CAIRO_FORMAT_RGB24
        CAIRO_FORMAT_A8
        CAIRO_FORMAT_A1
        CAIRO_FORMAT_RGB16_565
        CAIRO_FORMAT_RGB30

    unsigned char * cairo_image_surface_get_data(cairo_surface_t *surface)
    cairo_format_t cairo_image_surface_get_format(cairo_surface_t *surface)

    int cairo_image_surface_get_width (cairo_surface_t *surface)
    int cairo_image_surface_get_height (cairo_surface_t *surface)
    int cairo_image_surface_get_stride (cairo_surface_t *surface)

    void cairo_surface_flush (cairo_surface_t *surface)
    void cairo_surface_mark_dirty (cairo_surface_t *surface)
    int cairo_format_stride_for_width(cairo_format_t format, int width)

cdef extern from "pycairo/py3cairo.h":
    ctypedef struct Pycairo_CAPI_t:
        pass
    ctypedef struct PycairoSurface:
        #PyObject_HEAD
        cairo_surface_t *surface
        #PyObject *base; /* base object used to create surface, or NULL */
    ctypedef PycairoSurface PycairoImageSurface


CAIRO_FORMAT: Dict[cairo_format_t, str] = {
    CAIRO_FORMAT_INVALID    : "Invalid",
    CAIRO_FORMAT_ARGB32     : "ARGB32",
    CAIRO_FORMAT_RGB24      : "RGB24",
    CAIRO_FORMAT_A8         : "A8",
    CAIRO_FORMAT_A1         : "A1",
    CAIRO_FORMAT_RGB16_565  : "RGB16_565",
    CAIRO_FORMAT_RGB30      : "RGB30",
}


cdef void simple_copy(uintptr_t dst, uintptr_t src, int dst_stride, int src_stride, int height):
    cdef int stride = src_stride
    with nogil:
        if src_stride==dst_stride:
            memcpy(<void*> dst, <void*> src, stride*height)
        else:
            if dst_stride<src_stride:
                stride = dst_stride
            for _ in range(height):
                memcpy(<void*> dst, <void*> src, stride)
                src += src_stride
                dst += dst_stride


CAIRO_FORMATS: Dict[cairo_format_t, Sequence[str]] = {
    CAIRO_FORMAT_RGB24  : ("RGB", "RGBX", "BGR", "BGRX"),
    CAIRO_FORMAT_ARGB32 : ("BGRX", "BGRA"),
    CAIRO_FORMAT_RGB16_565  : ("BGR565", ),
    CAIRO_FORMAT_RGB30  : ("r210", ),
}


def make_image_surface(fmt, rgb_format: str, pixels, int width, int height, int stride) -> ImageSurface:
    if len(pixels)<height*stride:
        raise ValueError(f"pixel buffer is too small for {width}x{height} with stride={stride}:"+
                         f" only {len(pixels)} bytes, expected {height*stride}")

    cdef int x, y
    cdef int srci, dsti
    cdef const unsigned char * cbuf
    cdef cairo_surface_t * surface
    cdef unsigned char * cdata
    cdef cairo_format_t cairo_format
    cdef int istride
    cdef int iwidth
    cdef int iheight
    cdef cstride

    with buffer_context(pixels) as bc:
        if not bc.is_readonly():
            # maybe we can just create an ImageSurface directly:
            cstride = cairo_format_stride_for_width(fmt, width)
            if cstride == stride:
                return ImageSurface.create_for_data(pixels, fmt, width, height, stride)

        image_surface = ImageSurface(fmt, width, height)
        # convert pixel_data to a C buffer:
        # convert cairo.ImageSurface python object to a cairo_surface_t
        surface = (<PycairoImageSurface *> image_surface).surface
        cairo_surface_flush(surface)
        cdata = cairo_image_surface_get_data(surface)
        #get surface attributes:
        cairo_format = cairo_image_surface_get_format(surface)
        istride    = cairo_image_surface_get_stride(surface)
        iwidth     = cairo_image_surface_get_width(surface)
        iheight    = cairo_image_surface_get_height(surface)
        if iwidth != width or iheight != height:
            raise ValueError(f"invalid image surface: expected {width}x{height} but got {iwidth}x{iheight}")
        BPP = 2 if cairo_format == CAIRO_FORMAT_RGB16_565 else 4
        if istride < iwidth * BPP:
            raise ValueError(f"invalid image stride: expected at least {iwidth*4} but got {istride}")

        cbuf = <const unsigned char *> (<uintptr_t> int(bc))
        #only deal with the formats we care about:
        if cairo_format==CAIRO_FORMAT_RGB24:
            #cairo's RGB24 format is actually stored as BGR on little endian
            if rgb_format=="BGR":
                with nogil:
                    for y in range(iheight):
                        for x in range(iwidth):
                            srci = x*3 + y*stride
                            dsti = x*4 + y*istride
                            cdata[dsti + 0] = cbuf[srci + 0]     #B
                            cdata[dsti + 1] = cbuf[srci + 1]     #G
                            cdata[dsti + 2] = cbuf[srci + 2]     #R
                            cdata[dsti + 3] = 0xff               #X
            elif rgb_format=="RGB":
                with nogil:
                    for y in range(height):
                        for x in range(width):
                            srci = x*3 + y*stride
                            dsti = x*4 + y*istride
                            cdata[dsti + 0] = cbuf[srci + 2]     #B
                            cdata[dsti + 1] = cbuf[srci + 1]     #G
                            cdata[dsti + 2] = cbuf[srci + 0]     #R
                            cdata[dsti + 3] = 0xff               #X
            elif rgb_format=="BGRX":
                with nogil:
                    for y in range(height):
                        for x in range(width):
                            srci = x*4 + y*stride
                            dsti = x*4 + y*istride
                            cdata[dsti + 0] = cbuf[srci + 0]     #B
                            cdata[dsti + 1] = cbuf[srci + 1]     #G
                            cdata[dsti + 2] = cbuf[srci + 2]     #R
                            cdata[dsti + 3] = 0xff               #X
            elif rgb_format=="RGBX":
                with nogil:
                    for y in range(height):
                        for x in range(width):
                            srci = x*4 + y*stride
                            dsti = x*4 + y*istride
                            cdata[dsti + 0] = cbuf[srci + 2]     #B
                            cdata[dsti + 1] = cbuf[srci + 1]     #G
                            cdata[dsti + 2] = cbuf[srci + 0]     #R
                            cdata[dsti + 3] = 0xff               #X
            else:
                raise ValueError(f"unhandled pixel format for RGB24: {rgb_format!r}")
        elif cairo_format==CAIRO_FORMAT_ARGB32:
            if rgb_format in ("RGBA", "RGBX"):
                with nogil:
                    for y in range(height):
                        for x in range(width):
                            cdata[x*4 + 0 + y*istride] = cbuf[x*4 + 2 + y*stride]    #A
                            cdata[x*4 + 1 + y*istride] = cbuf[x*4 + 1 + y*stride]    #R
                            cdata[x*4 + 2 + y*istride] = cbuf[x*4 + 0 + y*stride]    #G
                            cdata[x*4 + 3 + y*istride] = cbuf[x*4 + 3 + y*stride]    #B
            elif rgb_format in ("BGRA", "BGRX"):
                simple_copy(<uintptr_t> cdata, <uintptr_t> cbuf, istride, stride, height)
            else:
                raise ValueError(f"unhandled pixel format for ARGB32: {rgb_format!r}")
        elif cairo_format==CAIRO_FORMAT_RGB30:
            if rgb_format in ("r210"):
                simple_copy(<uintptr_t> cdata, <uintptr_t> cbuf, istride, stride, height)
            #UNTESTED!
            #elif rgb_format in ("BGR48"):
            #access 16-bit per pixel at a time:
            #    sbuf = <unsigned short *> cbuf
            #    #write one pixel at a time: 30-bit padded to 32
            #    idata = <unsigned long*> cdata
            #    with nogil:
            #        for y in range(height):
            #            srci = y*stride
            #            dsti = y*istride
            #            for x in range(width):
            #                idata[dsti] = (sbuf[srci] & 0x3ff) + (sbuf[srci+1] & 0x3ff)<<10 + (sbuf[srci+2] & 0x3ff)<<20
            #                srci += 3
            #                dsti += 1
            else:
                raise ValueError(f"unhandled pixel format for RGB30 {rgb_format!r}")
        elif cairo_format==CAIRO_FORMAT_RGB16_565:
            if rgb_format in ("BGR565"):
                simple_copy(<uintptr_t> cdata, <uintptr_t> cbuf, istride, stride, height)
            else:
                raise ValueError(f"unhandled pixel format for RGB16_565 {rgb_format!r}")
        else:
            raise ValueError(f"unhandled cairo format {cairo_format!r}")
    cairo_surface_mark_dirty(surface)
    return image_surface


cdef Pycairo_CAPI_t * Pycairo_CAPI
Pycairo_CAPI = <Pycairo_CAPI_t*> PyCapsule_Import("cairo.CAPI", 0)
