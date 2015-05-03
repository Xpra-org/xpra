# This file is part of Xpra.
# Copyright (C) 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os


cython_bencode_loaded = False
if os.environ.get("USE_CYTHON_BENCODE", "1")!="0":
    try:
        from xpra.net.bencode.cython_bencode import bencode, bdecode, __version__
        cython_bencode_loaded = True
    except ImportError:
        pass
if not cython_bencode_loaded:
    from xpra.net.bencode.bencode import bencode, bdecode, __version__      #@Reimport

__all__ = ['bencode', 'bdecode', "__version__"]
