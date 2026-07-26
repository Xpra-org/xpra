# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from libc.stdint cimport int32_t

cdef extern from "pixman.h":
    # Basic types
    ctypedef int pixman_bool_t

    # Rectangle/box structure
    ctypedef struct pixman_box32_t:
        int32_t x1
        int32_t y1
        int32_t x2
        int32_t y2

    # Region structure (opaque, but we need to declare it)
    ctypedef struct pixman_region32_data_t:
        pass

    ctypedef struct pixman_region32_t:
        pixman_box32_t extents
        pixman_region32_data_t *data

    # Main function to get rectangles from a region
    pixman_box32_t* pixman_region32_rectangles(pixman_region32_t *region, int *n_rects)

    # Other useful region functions
    void pixman_region32_init(pixman_region32_t *region)
    void pixman_region32_fini(pixman_region32_t *region)
    pixman_bool_t pixman_region32_not_empty(pixman_region32_t *region)
    void pixman_region32_clear(pixman_region32_t *region)
