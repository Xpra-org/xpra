#!/usr/bin/env python
# This file is part of Parti.
# Copyright (C) 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk

from wimpiggy.log import Logger
log = Logger()

from tests.xpra.gl.gl_backing_test import gl_backing_test
from tests.xpra.gl.gl_simple_backing import GLTestBacking
from xpra.gl.gl_client_window import GLClientWindow
GLClientWindow.gl_pixmap_backing_class = GLTestBacking

"""
Note: the window isn't actually drawn at all when using GLTestBacking
"""
def main():
    import logging
    logging.basicConfig(format="%(message)s")
    logging.root.setLevel(logging.DEBUG)

    gl_backing_test(w=640, h=480)
    gtk.main()


if __name__ == '__main__':
    main()
