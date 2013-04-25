# This file is part of Xpra.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import logging
# This module is used by non-GUI programs and thus must not import gtk.

# A wrapper around 'logging' with some convenience stuff.  In particular:
#   -- You initialize it with a prefix (like "wimpiggy.window"), but can pass
#      a type= kwarg to any of the loggin methods to further specialize the
#      logging target (like "damage" to get "wimpiggy.window.damage").
#   -- You can pass exc_info=True to any method, and sys.exc_info() will be
#      substituted.
#   -- __call__ is an alias for debug
#   -- The default logging target is set to the name of the module where
#      Logger() was called.

class Logger(object):
    def __init__(self, base=None):
        if base is None:
            base = sys._getframe(1).f_globals["__name__"]
        self._base = base

    def getLogger(self, ltype=None):
        name = self._base
        if ltype:
            name += ". " + ltype
        return logging.getLogger(name)

    def log(self, level, msg, *args, **kwargs):
        if kwargs.get("exc_info") is True:
            kwargs["exc_info"] = sys.exc_info()
        self.getLogger().log(level, msg, *args, **kwargs)

    def _method_maker(level):           #@NoSelf
        return (lambda self, msg, *args, **kwargs:
                self.log(level, msg, *args, **kwargs))

    debug = _method_maker(logging.DEBUG)
    __call__ = debug
    info = _method_maker(logging.INFO)
    warn = _method_maker(logging.WARNING)
    error = _method_maker(logging.ERROR)
