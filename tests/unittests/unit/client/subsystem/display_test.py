#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch

from xpra.util.objects import AdHocStruct, typedict
from unit.test_util import silence_info
from unit.process_test_util import DisplayContext
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class DisplayClientTest(ClientMixinTest):

    def test_display(self):
        with DisplayContext():
            from xpra.client.subsystem import display  # pylint: disable=import-outside-toplevel

            def _DisplayClient():
                dc = display.DisplayClient()

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
            with silence_info(display):
                self._test_mixin_class(_DisplayClient, opts, {
                    "display" : ":999",
                    "desktop_size" : (1024, 768),
                    "max_desktop_size" : (3840, 2160),
                    "actual_desktop_size" : (1024, 768),
                    "resize_screen" : True,
                })

    def test_server_mode_capabilities(self):
        from xpra.client.subsystem import display
        display_caps = {
            "name": ":999",
            "desktop_size": (1920, 1080),
            "actual_desktop_size": (1920, 1080),
        }

        def parse(caps: dict, nested: bool):
            # Capability parsing itself does not need a display connection.
            with patch.object(display, "check_display"):
                dc = display.DisplayClient()
            if nested:
                caps = caps | {"display": display_caps}
            else:
                caps = display_caps | caps | {"display": ":999"}
            with silence_info(display):
                self.assertTrue(dc.parse_server_capabilities(typedict(caps)))
            return dc

        for nested in (False, True):
            with self.subTest(nested=nested):
                dc = parse({}, nested)
                self.assertFalse(dc.server_is_desktop)
                self.assertFalse(dc.server_is_monitor)
                self.assertFalse(dc.server_multi_monitors)
                for mode in ("shadow", "desktop"):
                    dc = parse({mode: True}, nested)
                    self.assertTrue(dc.server_is_desktop, mode)
                    self.assertFalse(dc.server_is_monitor, mode)
                monitors = {0: {"geometry": (0, 0, 1920, 1080)}}
                dc = parse({"monitor": True, "multi-monitors": True, "monitors": monitors}, nested)
                self.assertTrue(dc.server_is_desktop)
                self.assertTrue(dc.server_is_monitor)
                self.assertTrue(dc.server_multi_monitors)
                self.assertEqual(dc.server_monitors, monitors)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
