# This file is part of Parti.
# Copyright (C) 2010 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

try:
    from xpra.rencode._rencode import *
except ImportError:
    import xpra.rencode.rencode_orig
    prev_all = xpra.rencode.rencode_orig.__all__[:]
    del xpra.rencode.rencode_orig.__all__
    from xpra.rencode.rencode_orig import *
    xpra.rencode.rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
