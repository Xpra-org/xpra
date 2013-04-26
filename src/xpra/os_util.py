# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys

def set_prgname(name):
    try:
        import glib
        glib.set_prgname(name)
    except:
        pass


NAME_SET = False
def set_application_name(name):
    global NAME_SET
    if NAME_SET:
        return
    NAME_SET = True
    from wimpiggy.log import Logger
    log = Logger()
    if sys.version_info[:2]<(2,5):
        log.warn("Python %s is too old!", sys.version_info)
        return
    try:
        import glib
        glib.set_application_name(name or "Xpra")
    except ImportError, e:
        log.warn("glib is missing, cannot set the application name, please install glib's python bindings: %s", e)
