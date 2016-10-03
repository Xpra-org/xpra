#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.x11.bindings.display_source import clear_display      #@UnresolvedImport
from xpra.x11.bindings.posix_display_source import do_init_posix_display_source, close_display_source

class X11BindingsContext(object):

    def __init__(self, display_name):
        self.display_name = display_name
        self.display = 0

    def __enter__(self):
        self.display = do_init_posix_display_source(self.display_name)

    def __exit__(self, exc_type, exc_val, exc_tb):
        close_display_source(self.display)

    def __repr__(self):
        return "X11BindingsContext(%s)" % self.display_name

    def clear(self):
        clear_display()
