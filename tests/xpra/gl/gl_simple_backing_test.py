#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import pygtk
pygtk.require('2.0')
import gtk        #@UnusedImport

from xpra.log import Logger
log = Logger()

from tests.xpra.gl.gl_simple_client_window import GLSimpleClientWindow
from tests.xpra.gl.gl_backing_test import gl_backing_test

"""
Note: the window isn't actually drawn at all when using GLSimpleClientWindow
(which uses GLTestBacking)
"""
def main():
    import logging
    logging.root.setLevel(logging.DEBUG)

    gl_backing_test(gl_client_window_class=GLSimpleClientWindow, w=640, h=480)
    gtk.main()


if __name__ == '__main__':
    main()
