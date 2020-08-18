#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from unit.server_test_util import ServerTestUtil, log
from xpra.os_util import OSX, POSIX


class TestX11Keyboard(ServerTestUtil):

    def setUp(self):
        ServerTestUtil.setUp(self)
        display = self.find_free_display()
        self.xvfb = self.start_Xvfb(display)
        os.environ["DISPLAY"] = display
        os.environ["GDK_BACKEND"] = "x11"
        from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
        self.display_ptr = init_posix_display_source()

    def tearDown(self):
        ServerTestUtil.tearDown(self)
        from xpra.x11.bindings.posix_display_source import close_display_source         #@UnresolvedImport
        close_display_source(self.display_ptr)
        self.xvfb.terminate()


    def test_unicode(self):
        from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings        #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        for x in (
            "2030", "0005", "0010", "220F", "2039", "2211",
            "2248", "FB01", "F8FF", "203A", "FB02", "02C6",
            "02DA", "02DC", "2206", "2044", "25CA",
            ):
            #hex form:
            hk = keyboard_bindings.parse_keysym("0x"+x)
            #osx U+ form:
            uk = keyboard_bindings.parse_keysym("U+"+x)
            log("keysym(U+%s)=%#x, keysym(0x%s)=%#x", x, uk, x, hk)
            assert hk and uk
            assert uk == hk, "failed to get unicode keysym %s" % x

    def test_grok_modifier_map(self):
        from xpra.x11.gtk_x11.keys import grok_modifier_map
        from gi.repository.Gdk import Display
        display = Display.get_default()
        grok_modifier_map(display, None)
        grok_modifier_map(display, {})


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
