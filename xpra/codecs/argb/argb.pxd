# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2013-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

cdef argbdata_to_rgba(const unsigned char* argb, const int argb_len)  #pylint: disable=syntax-error
cdef argbdata_to_rgb(const unsigned char *argb, const int argb_len)
cdef bgradata_to_rgb(const unsigned char* bgra, const int bgra_len)
cdef bgradata_to_rgba(const unsigned char* bgra, const int bgra_len)
