# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("xor")

try:
    from xpra.codecs.xor.cyxor import xor_str  #@UnresolvedImport
    log("cyxor loaded")
except ImportError:
    log("cyxor not present")
    try:
        from xpra.codecs.xor.numpyxor import xor_str
        log("numpyxor loaded")
    except ImportError:
        log("numpyxor not present")
        raise Exception("xor support is missing: you must install numpy or compile the xpra.codecs.xor.cyxor module")
