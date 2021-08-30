#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX, OSX
from unit.test_util import silence_warn


class FakeXineramaTest(unittest.TestCase):

    def test_find(self):
        from xpra.x11.fakeXinerama import find_libfakeXinerama
        assert find_libfakeXinerama()

    def test_config(self):
        from xpra.x11 import fakeXinerama
        #silence warnings during tests:
        with silence_warn(fakeXinerama):
            def get_display_info(*monitors):
                #display_name, width, height, width_mm, height_mm, \
                #monitors, work_x, work_y, work_width, work_height = s[:11]
                return (
                    "fake-display",
                    1920, 1080, 400, 300,
                    monitors, 0, 60, 1920, 1020,
                    )
            monitor0 = ("plug0", 0, 0, 1920, 1080, 400, 300)
            monitor1 = ("plug1", 1920, 0, 1920, 1080, 300, 200)
            for ss in (
                get_display_info(),
                get_display_info((0, 0)),
                get_display_info(monitor0),
                get_display_info(monitor0, monitor1),
                (800, 600),
                (1, 2, 3, 4, 5),
                ):
                fakeXinerama.save_fakeXinerama_config(True, "", (ss, ))
                fakeXinerama.cleanup_fakeXinerama()


def main():
    #can only work with an X11 server
    if POSIX and not OSX:
        unittest.main()

if __name__ == '__main__':
    main()
