# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
cython_rencode_loaded = False
if os.environ.get("USE_CYTHON_RENCODE", "1")!="0":
    try:
        from xpra.net.rencode.rencode import *
        from xpra.net.rencode.rencode import __version__
        cython_rencode_loaded = True
    except ImportError:
        pass
if not cython_rencode_loaded:
    import rencode_orig
    prev_all = rencode_orig.__all__[:]
    del rencode_orig.__all__
    from rencode_orig import *
    from rencode_orig import __version__        #@Reimport
    rencode_orig.__all__ = prev_all

__all__ = ['dumps', 'loads']
