# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

try:
    from xpra.codecs.xor.cyxor import xor_str  #@UnresolvedImport
    log("cyxor loaded")
except ImportError, e:
    log("cyxor not present")
    try:
        from xpra.codecs.xor.numpyxor import xor_str
        log("numpyxor loaded")
    except ImportError, e:
        log("numpyxor not present")
        try:
            bytearray()
        except NameError:
            raise Exception("your python version lacks the bytearray type, you must install numpy or compile the xpra.xor.cyxor module")
        log.warn("using python xor fallback (much slower)")
        def xor_str(a, b):
            assert len(a)==len(b), "cannot xor strings of different lengths (pyxor)"
            c = bytearray("\0"*len(a))
            for i in range(len(a)):
                c[i] = ord(a[i])^ord(b[i])
            return str(c)
