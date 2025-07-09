# This file is part of Xpra.
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

cdef memoryview argbdata_to_rgba(const unsigned int* argb, const int argb_len)  #pylint: disable=syntax-error
cdef memoryview argbdata_to_rgb(const unsigned int* argb, const int argb_len)
cdef memoryview bgradata_to_rgb(const unsigned int* bgra, const int bgra_len)
cdef memoryview bgradata_to_rgba(const unsigned int* bgra, const int bgra_len)

cdef void show_plane_range(name, plane: SizedBuffer, unsigned int width, unsigned int stride, unsigned int height)
