# This file is part of Xpra.
# Copyright (C) 2014-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=import-outside-toplevel

bencode = None
bdecode = None
__version__ = 0

def init():
    global bencode, bdecode, __version__
    from xpra.util import envbool
    cython_bencode_loaded = False
    if envbool("XPRA_USE_CYTHON_BENCODE", True):
        try:
            from xpra.net.bencode.cython_bencode import (
                bencode as cbencode,
                bdecode as cbdecode,
                __version__ as cversion,
                )
            bencode = cbencode
            bdecode = cbdecode
            __version__ = cversion
            cython_bencode_loaded = True
        except ImportError as e:
            from xpra.os_util import get_util_logger
            get_util_logger().warn("Warning: cannot load cython bencode module: %s", e)
    if not cython_bencode_loaded:
        from xpra.net.bencode.bencode import (
            bencode as pbencode,
            bdecode as pbdecode,
            __version__ as pversion,
            )
        bencode = pbencode
        bdecode = pbdecode
        __version__ = pversion

init()

__all__ = ['bencode', 'bdecode', "__version__"]
