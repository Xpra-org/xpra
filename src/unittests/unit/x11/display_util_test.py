#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from unit.server_test_util import ServerTestUtil
from xpra.os_util import POSIX, OSX, OSEnvContext


class TestDisplayUtil(ServerTestUtil):

    def test_display(self):
        from xpra.x11.gtk3.gdk_display_util import verify_gdk_display
        with OSEnvContext():
            os.environ["GDK_BACKEND"] = "x11"
            try:
                del os.environ["DISPLAY"]
            except KeyError:
                pass
            for d in (None, ""):
                try:
                    verify_gdk_display(d)
                except Exception:
                    pass
                else:
                    raise Exception("%s is not a valid display" % d)

            display = self.find_free_display()
            xvfb = self.start_Xvfb(display)
            os.environ["DISPLAY"] = display
            from xpra.x11.bindings.posix_display_source import X11DisplayContext    #@UnresolvedImport
            with X11DisplayContext(display):
                verify_gdk_display(display)
            xvfb.terminate()


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
