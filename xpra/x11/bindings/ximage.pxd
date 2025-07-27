# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.xlib cimport XImage
from libc.stdint cimport uint64_t


cdef inline unsigned int roundup(unsigned int n, unsigned int m) noexcept:
    return (n + m - 1) & ~(m - 1)


cdef inline unsigned char BYTESPERPIXEL(unsigned int depth) noexcept:
    if depth>=24 and depth<=32:
        return 4
    elif depth==16:
        return 2
    elif depth==8:
        return 1
    #shouldn't happen!
    return roundup(depth, 8)//8


cdef inline unsigned int MIN(unsigned int a, unsigned int b) noexcept:
    if a<=b:
        return a
    return b


ctypedef unsigned long CARD32
ctypedef CARD32 Colormap
DEF XNone = 0


cdef class XImageWrapper:
    """
        Presents X11 image pixels as in ImageWrapper
    """

    cdef XImage *image
    cdef unsigned int x
    cdef unsigned int y
    cdef unsigned int target_x
    cdef unsigned int target_y
    cdef unsigned int width
    cdef unsigned int height
    cdef unsigned int depth
    cdef unsigned int rowstride
    cdef unsigned int planes
    cdef unsigned int bytesperpixel
    cdef unsigned char thread_safe
    cdef unsigned char sub
    cdef object pixel_format
    cdef void *pixels
    cdef object del_callback
    cdef uint64_t timestamp
    cdef object palette
    cdef unsigned char full_range
    cdef unsigned char aligned

    cdef void set_image(self, XImage* image)

    cdef void* get_pixels_ptr(self)

    cdef void free_image(self)

    cdef void free_pixels(self)
