# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import logging
# This module is used by non-GUI programs and thus must not import gtk.

# A wrapper around 'logging' with some convenience stuff.  In particular:
#   -- You initialize it with a prefix (like "xpra.window")
#      If unset, the default logging target is set to the name of the module where
#      Logger() was called.
#   -- You can pass exc_info=True to any method, and sys.exc_info() will be
#      substituted.
#   -- __call__ is an alias for debug

class Logger(object):
    def __init__(self, base=None):
        if base is None:
            base = sys._getframe(1).f_globals["__name__"]
        self._base = base
        self.logger = logging.getLogger(self._base)

    def log(self, level, msg, *args, **kwargs):
        if kwargs.get("exc_info") is True:
            kwargs["exc_info"] = sys.exc_info()
        self.logger.log(level, msg, *args, **kwargs)

    def _method_maker(level):           #@NoSelf
        return (lambda self, msg, *args, **kwargs:
                self.log(level, msg, *args, **kwargs))

    debug = _method_maker(logging.DEBUG)
    __call__ = debug
    info = _method_maker(logging.INFO)
    warn = _method_maker(logging.WARNING)
    error = _method_maker(logging.ERROR)


#utility function returning a logging function whose logging level
#depends on the value of the environment variable given
#(info if set to "1", debug otherwise)
def debug_if_env(log, env_name):
    if os.environ.get(env_name, "0")=="1":
        return log.info
    else:
        return log.debug
