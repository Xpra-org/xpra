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
        # `XPRA_TEST_VFB_COMMAND` can be used to test the `Xvfb` code paths
        # on distributions where we would otherwise use `Xdummy`:
        ServerTestUtil.test_xvfb_command = os.environ.get("XPRA_TEST_VFB_COMMAND") or (
            "Xdummy" if FULL_TEST else "Xvfb")
        xvfb = self.start_Xvfb(display)
        time.sleep(1)
        assert display in self.find_X11_displays()
        return display, xvfb

    def test_resize(self):
        with OSEnvContext():

            display, xvfb = self.start_test_xvfb()
            log.warn("test resize on display: %s", display)
            from xpra.x11.bindings.display_source import (
                set_display_name, init_display_source, close_display_source,
            )
            display_ptr = 0
            try:
                os.environ["DISPLAY"] = display
                set_display_name(display)
                display_ptr = init_display_source()

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

                # `set_crtc_config` can configure a single monitor on any RandR 1.5 display,
                # more than one monitor requires the dummy driver's 16 crtcs:
                version = randr.get_version()
                if version < (1, 5):
                    log.warn("RandR version %s is too old to configure monitors", version)
                    return
                dummy16 = randr.is_dummy16()
                if not dummy16:
                    log.warn("no dummy 1.6 support: only testing single monitor configurations")

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
                    # applying the same configuration again must be recognized as a no-op:
                    assert randr.is_current_monitor_config(config), f"{config} should already be applied"

                def same_config(current: dict, changes: dict) -> dict:
                    updated = {index: dict(monitor) for index, monitor in current.items()}
                    for index, monitor in changes.items():
                        updated.setdefault(index, {}).update(monitor)
                    return updated

                def assert_current(expected: bool, config: dict, msg: str) -> None:
                    assert randr.is_current_monitor_config(config) == expected, f"{msg}: {config}"

                test_crtc_config(751, 1122, {
                    0: {'geometry': (0, 0, 751, 1122), 'x': 0, 'y': 0, 'width': 751, 'height': 1122,
                        'name': 'VFB-0', 'index': 0},
                })

                test_crtc_config(1383, 1476, {
                    0: {'name': 'Canvas', 'geometry': (0, 0, 1383, 1476), 'width-mm': 366, 'height-mm': 391},
                })

                test_crtc_config(790, 774, {
                    0: {'name': 'Foo', 'geometry': (0, 0, 790, 774), 'width-mm': 209, 'height-mm': 205},
                })

                if dummy16:
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
                test_crtc_config(1024, 768, {
                    0: {'name': 'SVGA', 'geometry': (0, 0, 1024, 768), 'width-mm': 150, 'height-mm': 120},
                })
                test_crtc_config(1024, 768, {
                    0: {'name': 'SVGA', 'geometry': (0, 0, 1024, 768), 'width-mm': 150, 'height-mm': 120},
                })

                # `is_current_monitor_config` decides if `set_crtc_config` can be skipped:
                single = {
                    0: {'name': 'DP-0', 'geometry': (0, 0, 1600, 900), 'primary': True,
                        'width-mm': 209, 'height-mm': 205, 'refresh-rate': 59951},
                }
                test_crtc_config(1600, 900, single)
                # the plug name is not part of the configuration we compare:
                assert_current(True, same_config(single, {0: {"name": "eDP-1"}}),
                               "the plug name must be ignored")
                # neither is the jitter in the refresh rates reported by the clients:
                assert_current(True, same_config(single, {0: {"refresh-rate": 59952}}),
                               "a refresh rate rounding down to the same Hz must be ignored")
                assert_current(True, same_config(single, {0: {"refresh-rate": 60049}}),
                               "a refresh rate rounding up to the same Hz must be ignored")
                # but everything else must be applied:
                assert_current(False, same_config(single, {0: {"refresh-rate": 50000}}),
                               "a different refresh rate must be applied")
                assert_current(False, same_config(single, {0: {"geometry": (0, 0, 1600, 1200)}}),
                               "a different geometry must be applied")
                assert_current(False, same_config(single, {0: {"width-mm": 500}}),
                               "different physical dimensions must be applied")
                assert_current(False, same_config(single, {1: {'name': 'DP-1', 'geometry': (1600, 0, 1280, 1024)}}),
                               "adding a monitor must be applied")

                if dummy16:
                    dual = same_config(single, {
                        1: {'name': 'DP-1', 'geometry': (1600, 0, 1280, 1024),
                            'width-mm': 209, 'height-mm': 205, 'refresh-rate': 60000},
                    })
                    test_crtc_config(2880, 1024, dual)
                    assert_current(True, same_config(dual, {0: {"name": "eDP-1"}, 1: {"name": "HDMI-A-2"}}),
                                   "the plug names must be ignored")
                    assert_current(False, same_config(dual, {0: {"primary": False}, 1: {"primary": True}}),
                                   "a different primary monitor must be applied")
                    assert_current(False, {0: dual[0]},
                                   "removing a monitor must be applied")

            finally:
                if display_ptr:
                    # close the connection before killing the Xvfb,
                    # or the dangling display pointer will terminate this process
                    # with an X11 IO error the next time the bindings are used:
                    close_display_source(display_ptr)
                xvfb.terminate()


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
