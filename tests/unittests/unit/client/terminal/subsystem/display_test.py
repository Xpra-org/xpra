#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Yan Shoshitaishvili <yans@pwn.college>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import unittest

from xpra.util.env import OSEnvContext
from xpra.util.objects import AdHocStruct
from xpra.client.subsystem import display as base_display
from unit.test_util import silence_info
from unit.client.subsystem.clientmixintest_util import ClientMixinTest

try:
    from xpra.client.terminal.subsystem import display as terminal_display
except ImportError:
    terminal_display = None

# the pixel size of the terminal used by these tests:
TERMINAL_SIZE = (1024, 600)

SERVER_CAPS = {
    "display": ":999",
    "desktop_size": (1024, 600),
    "max_desktop_size": (3840, 2160),
    "actual_desktop_size": (1024, 600),
    "resize_screen": True,
}


@unittest.skipIf(terminal_display is None, "the terminal client component is not available")
class TerminalDisplayClientTest(ClientMixinTest):

    def terminal_pixel_size(self) -> tuple[int, int]:
        # this test class stands in for the client: like the real client before
        # the first terminal reading, it has no pixel size to report
        # (the tests override this with the size they need):
        return 0, 0

    def setUp(self):
        super().setUp()
        # the terminal client never initializes an X11 display source, so the platform
        # queries used by the display capabilities (`get_wm_name`, `get_vrefresh`, ...)
        # must not go looking for one - the client declares that with `XPRA_NOX11`,
        # just like `xpra.platform.posix.shadow_server` does:
        env_context = OSEnvContext(XPRA_NOX11="1")
        env_context.__enter__()
        self.addCleanup(env_context.__exit__)

    def make_opts(self):
        opts = AdHocStruct()
        opts.desktop_fullscreen = False
        # a TRUE option, so that `init` parses the scaling,
        # which calls `get_root_size()` before the client is in terminal mode:
        opts.desktop_scaling = "on"
        opts.dpi = 96
        opts.refresh_rate = "auto"
        # the default on POSIX, which would start the X11 property watcher:
        opts.xsettings = "auto"
        return opts

    def init_mixin(self, opts=None):
        opts = opts or self.make_opts()
        with silence_info(base_display):
            self._test_mixin_class(terminal_display.TerminalDisplayClient, opts, SERVER_CAPS)
        return opts

    def test_root_size(self):
        self.terminal_pixel_size = lambda: TERMINAL_SIZE
        self.init_mixin()
        self.assertEqual(self.mixin.get_root_size(), TERMINAL_SIZE)
        self.assertEqual(tuple(self.mixin.get_screen_sizes()), (TERMINAL_SIZE, ))
        self.assertEqual(tuple(self.mixin.get_screen_sizes(2, 2)), ((512, 300), ))
        self.assertTrue(self.mixin.has_transparency())
        self.assertEqual((self.mixin.xscale, self.mixin.yscale), (1, 1))

    def test_root_size_default(self):
        # a terminal which does not know its pixel size yet reports zeroes,
        # and the default geometry constants take over:
        self.init_mixin()
        default_size = terminal_display.DEFAULT_ROOT_SIZE
        self.assertEqual(default_size, (terminal_display.DEFAULT_COLUMNS * terminal_display.DEFAULT_CELL_WIDTH,
                                        terminal_display.DEFAULT_ROWS * terminal_display.DEFAULT_CELL_HEIGHT))
        self.assertEqual(self.mixin.get_root_size(), default_size)

    def test_no_xsettings_watcher(self):
        opts = self.init_mixin()
        # `X11DisplayPropsWatcher` must never be started by a terminal client:
        self.assertEqual(opts.xsettings, "no")
        self.assertIsNone(self.mixin._x11_props)

    def test_monitors_info(self):
        self.terminal_pixel_size = lambda: TERMINAL_SIZE
        self.init_mixin()
        monitors = self.mixin.get_monitors_info()
        self.assertEqual(tuple(monitors.keys()), (0, ))
        monitor = monitors[0]
        self.assertEqual(monitor["name"], "terminal")
        self.assertEqual(monitor["geometry"], (0, 0) + TERMINAL_SIZE)
        self.assertEqual(monitor["workarea"], (0, 0) + TERMINAL_SIZE)
        self.assertTrue(monitor["primary"])
        self.assertGreater(monitor["refresh-rate"], 0)
        self.assertGreater(monitor["width-mm"], 0)
        self.assertGreater(monitor["height-mm"], 0)
        # this must not load any toolkit:
        self.assertNotIn("xpra.gtk.info", sys.modules)
        # the geometry is in server coordinate space:
        self.mixin.xscale = self.mixin.yscale = 2
        self.assertEqual(self.mixin.get_monitors_info()[0]["geometry"], (0, 0, 512, 300))

    def test_caps(self):
        self.terminal_pixel_size = lambda: TERMINAL_SIZE
        self.init_mixin()
        with silence_info(base_display):
            caps = self.mixin.get_caps()
        self.assertEqual(caps["desktop_size"], TERMINAL_SIZE)
        self.assertEqual(caps["monitors"][0]["geometry"], (0, 0) + TERMINAL_SIZE)
        self.assertTrue(caps["resize-events"])
        # the server capabilities were parsed by `_test_mixin_class`:
        self.assertEqual(self.mixin.server_display, ":999")
        self.assertEqual(self.mixin.server_max_desktop_size, (3840, 2160))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
