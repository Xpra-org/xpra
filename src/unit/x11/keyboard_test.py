#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest


class TestX11Keyboard(unittest.TestCase):

    def test_unicode(self):
        if not os.name=="posix":
            #can only work with an X11 server
            return
        try:
            from xpra.x11.bindings import posix_display_source      #@UnusedImport
        except Exception as e:
            print("failed to initialize the display source: %s" % e)
            print("no X11 server available for this test? (skipped)")
            return
        from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings        #@UnresolvedImport
        keyboard_bindings = X11KeyboardBindings()
        for x in ("2030", "0005", "0010", "220F", "2039", "2211", "2248", "FB01", "F8FF", "203A", "FB02", "02C6", "02DA", "02DC", "2206", "2044", "25CA"):
            #hex form:
            hk = keyboard_bindings.parse_keysym("0x"+x)
            #print("keysym(0x%s)=%s" % (x, hk))
            #osx U+ form:
            uk = keyboard_bindings.parse_keysym("U+"+x)
            #print("keysym(U+%s)=%s" % (x, uk))
            assert hk and uk
            assert uk == hk, "failed to get unicode keysym %s" % x


def main():
    unittest.main()

if __name__ == '__main__':
    main()
