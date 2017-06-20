#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from unit.server_test_util import ServerTestUtil, log
from xpra.os_util import OSX, POSIX


class TestX11Keyboard(ServerTestUtil):

    def test_unicode(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        from unit.x11.x11_test_util import X11BindingsContext
        with X11BindingsContext(display):
            from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings        #@UnresolvedImport
            keyboard_bindings = X11KeyboardBindings()
            for x in ("2030", "0005", "0010", "220F", "2039", "2211", "2248", "FB01", "F8FF", "203A", "FB02", "02C6", "02DA", "02DC", "2206", "2044", "25CA"):
                #hex form:
                hk = keyboard_bindings.parse_keysym("0x"+x)
                #osx U+ form:
                uk = keyboard_bindings.parse_keysym("U+"+x)
                log("keysym(U+%s)=%s" % (x, uk))
                assert hk and uk
                assert uk == hk, "failed to get unicode keysym %s" % x
        xvfb.terminate()


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
