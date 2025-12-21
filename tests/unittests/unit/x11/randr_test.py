#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2016 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
import unittest

from xpra.os_util import OSX, POSIX
from unit.server_test_util import ServerTestUtil
from xpra.log import Logger
from xpra.util.env import OSEnvContext
from xpra.util.system import is_Debian, is_Ubuntu

log = Logger("randr")

FULL_TEST = not (is_Debian() or is_Ubuntu())


class RandrTest(ServerTestUtil):

    def start_test_xvfb(self, *args):
        display = self.find_free_display()
        ServerTestUtil.test_xvfb_command = "Xdummy" if FULL_TEST else "Xvfb"
        xvfb = self.start_Xvfb(display)
        time.sleep(1)
        assert display in self.find_X11_displays()
        return display, xvfb

    def test_resize(self):
        with OSEnvContext():

            display, xvfb = self.start_test_xvfb()
            log.warn("test resize on display: %s", display)
            try:
                os.environ["DISPLAY"] = display
                from xpra.x11.bindings.display_source import set_display_name, init_display_source
                set_display_name(display)
                init_display_source()

                from xpra.x11.bindings.randr import RandRBindings
                randr = RandRBindings()
                if not randr.has_randr():
                    log.warn("no RandR support!")
                    return
                log("randr version: %s", randr.get_version())
                log("screen sizes: %s", randr.get_xrr_screen_sizes())
                log("screen count: %s", randr.get_screen_count())
                log("screen size mm: %s", randr.get_screen_size_mm())
                log("vrefresh: %s", randr.get_vrefresh())
                log("display vrefresh: %s", randr.get_vrefresh_display())

                if not randr.is_dummy16():
                    log.warn("no dummy 1.6 support!")
                    return
                log("dummy 1.6 driver, testing monitor configs")

                def test_crtc_config(w: int, h: int, config: dict) -> None:
                    assert not randr.has_mode(w, h)
                    randr.set_crtc_config(config)
                    assert randr.has_mode(w, h)
                    assert randr.get_screen_size() == (w, h), f"expected {w}x{h}, got {randr.get_screen_size()}"

                test_crtc_config(751, 1122,{
                    0: {'geometry': (0, 0, 751, 1122), 'x': 0, 'y': 0, 'width': 751, 'height': 1122,
                        'name': 'VFB-0', 'index': 0}
                })

                test_crtc_config(1383, 1476, {
                    0: {'name': 'Canvas', 'geometry': (0, 0, 1383, 1476), 'width-mm': 366, 'height-mm': 391}
                })

                # html5 client random screen sizes - cannot be one of the default sizes:
                test_crtc_config(790, 774, {
                    0: {'name': 'Foo', 'geometry': (0, 0, 790, 774), 'width-mm': 209, 'height-mm': 205}
                })

            finally:
                xvfb.terminate()


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
