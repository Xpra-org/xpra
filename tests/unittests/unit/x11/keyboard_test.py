#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011-2022 Antoine Martin <antoine@xpra.org>
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
        from xpra.x11.bindings.posix_display_source import init_posix_display_source    #@UnresolvedImport
        cls.display_ptr = init_posix_display_source()
        from xpra.x11.gtk3.gdk_display_util import verify_gdk_display
        verify_gdk_display(display)

    @classmethod
    def tearDownClass(cls):
        from xpra.x11.bindings.posix_display_source import close_display_source         #@UnresolvedImport
        close_display_source(cls.display_ptr)
        ServerTestUtil.tearDownClass()
        cls.xvfb.terminate()


    def test_unicode(self):
        from xpra.x11.bindings.keyboard import X11KeyboardBindings        #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        for x in (
                "2030", "220F", "2039", "2211",
                "2248", "FB01", "F8FF", "203A", "FB02", "02C6",
                "02DA", "02DC", "2206", "2044", "25CA",
        ):
            # osx U+ form:
            uk = keyboard_bindings.parse_keysym("U+" + x)
            # unicode keysyms are offset by 0x1000000:
            hk = keyboard_bindings.parse_keysym("0x1" + x.zfill(6))
            log("keysym(U+%s)=%#x, keysym(0x1%s)=%#x", x, uk, x.zfill(6), hk)
            assert uk == hk == 0x1000000 + int(x, 16), "failed to get unicode keysym %s" % x
        # latin-1 characters use the legacy keysyms:
        assert keyboard_bindings.parse_keysym("U+00E9") == keyboard_bindings.parse_keysym("eacute") == 0xe9
        # control characters are not keysyms:
        for x in ("0005", "0010"):
            assert keyboard_bindings.parse_keysym("U+" + x) == 0, "U+%s should not be a keysym" % x

    def test_grok_modifier_map(self):
        from xpra.x11.gtk_x11.keys import grok_modifier_map
        from gi.repository.Gdk import Display  # @UnresolvedImport
        display = Display.get_default()
        grok_modifier_map(display, None)
        grok_modifier_map(display, {})


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
