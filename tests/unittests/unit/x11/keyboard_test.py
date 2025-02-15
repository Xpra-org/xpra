#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from unit.server_test_util import ServerTestUtil, log
from xpra.os_util import OSX, POSIX


class TestX11Keyboard(ServerTestUtil):

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        display = cls.find_free_display()
        cls.xvfb = cls.start_Xvfb(display)
        os.environ["DISPLAY"] = display
        os.environ["GDK_BACKEND"] = "x11"
        from xpra.x11.bindings.posix_display_source import init_posix_display_source  #@UnresolvedImport
        cls.display_ptr = init_posix_display_source()
        from xpra.scripts.server import verify_gdk_display
        verify_gdk_display(display)

    @classmethod
    def tearDownClass(cls):
        from xpra.x11.bindings.posix_display_source import close_display_source  #@UnresolvedImport
        close_display_source(cls.display_ptr)
        ServerTestUtil.tearDownClass()
        cls.xvfb.terminate()

    def test_unicode(self):
        from xpra.x11.bindings.keyboard import X11KeyboardBindings  #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        for x in (
                "2030", "0005", "0010", "220F", "2039", "2211",
                "2248", "FB01", "F8FF", "203A", "FB02", "02C6",
                "02DA", "02DC", "2206", "2044", "25CA",
        ):
            #hex form:
            hk = keyboard_bindings.parse_keysym("0x" + x)
            #osx U+ form:
            uk = keyboard_bindings.parse_keysym("U+" + x)
            log("keysym(U+%s)=%#x, keysym(0x%s)=%#x", x, uk, x, hk)
            assert hk and uk
            assert uk == hk, "failed to get unicode keysym %s" % x

    def test_grok_modifier_map(self):
        from xpra.x11.gtk.keys import grok_modifier_map
        grok_modifier_map(None)
        grok_modifier_map({})


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
