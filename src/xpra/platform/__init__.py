# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

import os as os
import sys as sys
from xpra.log import Logger
log = Logger()
debug = log.debug
if os.environ.get("XPRA_IMPORT_DEBUG", "0")=="1":
    debug = log.info

_init_done = False
def init():
    global _init_done
    if not _init_done:
        _init_done = True
        do_init()

def do_init():
    pass


def platform_import(where, pm, required, *imports):
    if os.name == "nt":
        p = "win32"
    elif sys.platform.startswith("darwin"):
        p = "darwin"
    elif os.name == "posix":
        p = "xposix"
    else:
        raise OSError("Unknown OS %s" % (os.name))

    module = "xpra.platform.%s" % p
    if pm:
        module += ".%s" % pm
    debug("importing %s from %s (required=%s)" % (imports, module, required))
    platform_module = __import__(module, {}, {}, imports)
    assert platform_module
    for x in imports:
        found = hasattr(platform_module, x)
        if not found:
            if required:
                raise Exception("could not find %s in %s" % (x, module))
            else:
                debug("%s=%s (unchanged)" % (x, where[x]))
                continue
        v = getattr(platform_module, x)
        debug("%s=%s" % (x, str(v).replace("\n", "\\n")))
        where[x] = v

platform_import(globals(), None, True, "do_init")
