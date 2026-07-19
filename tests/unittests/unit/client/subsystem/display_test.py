#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.test_util import silence_info, stubbable
from unit.process_test_util import DisplayContext
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class DisplayClientTest(ClientMixinTest):

    def test_display(self):
        with DisplayContext():
            from xpra.client.subsystem import display  # pylint: disable=import-outside-toplevel

            def _DisplayClient():
                # `get_root_size` / `get_screen_sizes` are this subsystem's own
                # methods, so stub them on a `stubbable` instance:
                dc = stubbable(display.DisplayClient)()

                def get_root_size():
                    return 1024, 768
                dc.get_root_size = get_root_size

                def get_screen_sizes(*_args):
                    return ((1024, 768),)
                dc.get_screen_sizes = get_screen_sizes
                return dc
            opts = AdHocStruct()
            opts.desktop_fullscreen = False
            opts.desktop_scaling = False
            opts.dpi = 144
            opts.refresh_rate = "20"
            opts.xsettings = False
            with silence_info(display):
                self._test_mixin_class(_DisplayClient, opts, {
                    "display" : ":999",
                    "desktop_size" : (1024, 768),
                    "max_desktop_size" : (3840, 2160),
                    "actual_desktop_size" : (1024, 768),
                    "resize_screen" : True,
                })
            # `get_monitors_info` now calls through to `xpra.platform.gui.get_monitors_info`
            # rather than returning `{}` unconditionally (see the toolkit-split plan):
            called = []

            def fake_get_monitors_info(xscale, yscale):
                called.append((xscale, yscale))
                return {0: {"geometry": (0, 0, 1024, 768)}}
            import xpra.platform.gui as platform_gui
            orig = platform_gui.get_monitors_info
            platform_gui.get_monitors_info = fake_get_monitors_info
            try:
                info = self.mixin.get_monitors_info()
            finally:
                platform_gui.get_monitors_info = orig
            self.assertEqual(called, [(self.mixin.xscale, self.mixin.yscale)])
            self.assertEqual(info, {0: {"geometry": (0, 0, 1024, 768)}})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
