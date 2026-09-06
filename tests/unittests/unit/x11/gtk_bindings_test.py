#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from unit.server_test_util import ServerTestUtil
from xpra.os_util import POSIX, OSX
from xpra.util.env import OSEnvContext


class TestX11GtkBindings(ServerTestUtil):

    def test_cleanup_filter_without_init(self):
        from xpra.gtk.util import open_gdk_display
        with OSEnvContext():
            os.environ["GDK_BACKEND"] = "x11"
            display = self.find_free_display()
            xvfb = self.start_Xvfb(display)
            os.environ["DISPLAY"] = display
            from xpra.x11.bindings.display_source import X11DisplayContext    #@UnresolvedImport
            with X11DisplayContext(display):
                gdk_display = open_gdk_display(display)
                try:
                    from xpra.x11.gtk.bindings import init_x11_filter, cleanup_x11_filter   #@UnresolvedImport
                    # an unmatched `cleanup_x11_filter` must not take the reference
                    # count negative, or the `init_x11_filter` that follows would
                    # hand out a lease without ever installing the event filter:
                    self.assertFalse(cleanup_x11_filter())
                    self.assertTrue(init_x11_filter())
                    self.assertTrue(cleanup_x11_filter())
                finally:
                    if gdk_display:
                        # as in `display_util_test`: close the connection and drop
                        # the reference before the Xvfb goes away, or GDK's final
                        # `XSync` kills this process
                        gdk_display.close()
                        del gdk_display
            xvfb.terminate()


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
