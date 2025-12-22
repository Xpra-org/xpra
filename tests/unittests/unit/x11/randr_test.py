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
                    log("test_crtc_config(%i, %i, %s", w, h, config)
                    randr.set_crtc_config(config)
                    for monitor in config.values():
                        mw, mh = monitor["geometry"][2:4]
                        assert randr.has_mode(mw, mh)
                    assert randr.get_screen_size() == (w, h), f"expected {w}x{h}, got {randr.get_screen_size()}"
                    retrieved = randr.get_monitor_properties()
                    assert len(retrieved) == len(config), "expected %i monitors configured but got %i: %s vs %s" % (
                        len(config), len(retrieved), config, retrieved,
                    )

                test_crtc_config(751, 1122,{
                    0: {'geometry': (0, 0, 751, 1122), 'x': 0, 'y': 0, 'width': 751, 'height': 1122,
                        'name': 'VFB-0', 'index': 0},
                })

                test_crtc_config(1383, 1476, {
                    0: {'name': 'Canvas', 'geometry': (0, 0, 1383, 1476), 'width-mm': 366, 'height-mm': 391},
                })

                test_crtc_config(790, 774, {
                    0: {'name': 'Foo', 'geometry': (0, 0, 790, 774), 'width-mm': 209, 'height-mm': 205},
                })

                # dual monitor
                test_crtc_config(3840, 1080, {
                    0: {'name': 'DP-0', 'geometry': (0, 0, 1920, 1080), 'width-mm': 209, 'height-mm': 205},
                    1: {'name': 'HDMI-1', 'geometry': (1920, 0, 1920, 1080),
                        'width-mm': 209, 'height-mm': 205, 'refresh-rate': 144000},
                })

                test_crtc_config(4480, 2160, {
                    0: {'name': 'VGA', 'geometry': (0, 0, 640, 480),
                        'width-mm': 100, 'height-mm': 80, 'refresh-rate': 50000},
                    1: {'name': 'DP-1', 'geometry': (640, 0, 3840, 2160), 'width-mm': 209, 'height-mm': 205},
                })

                # single again:
                test_crtc_config(1024, 768,{
                    0: {'name': 'SVGA', 'geometry': (0, 0, 1024, 768), 'width-mm': 150, 'height-mm': 120},
                })
                test_crtc_config(1024, 768,{
                    0: {'name': 'SVGA', 'geometry': (0, 0, 1024, 768), 'width-mm': 150, 'height-mm': 120},
                })

            finally:
                xvfb.terminate()


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
