# This file is part of Xpra.
# Copyright (C) 2015-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#cython: language_level=3

cdef override_logger()  #pylint: disable=syntax-error
cdef restore_logger()

cdef av_error_str(int errnum)
