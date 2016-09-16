# This file is part of Xpra.
# Copyright (C) 2014-2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.util import envbool
cython_bencode_loaded = False
if envbool("XPRA_USE_CYTHON_BENCODE", True):
    try:
        from xpra.net.bencode.cython_bencode import bencode, bdecode, __version__
        cython_bencode_loaded = True
    except ImportError as e:
        from xpra.log import Logger
        log = Logger("network")
        log.warn("cannot load cython bencode module: %s", e)
if not cython_bencode_loaded:
    from xpra.net.bencode.bencode import bencode, bdecode, __version__      #@Reimport

__all__ = ['bencode', 'bdecode', "__version__"]
