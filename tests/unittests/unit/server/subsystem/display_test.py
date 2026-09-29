#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class DisplayMixinTest(ServerMixinTest):

    def test_display(self):
        with DisplayContext():
            self.do_test_display()

    def do_test_display(self):
        from xpra.server.subsystem.display import DisplayManager
        from xpra.server.source.display import DisplayConnection
        opts = AdHocStruct()
        opts.bell = True
        opts.cursors = True
        opts.dpi = 144
        opts.opengl = "no"
        opts.refresh_rate = "auto"
        opts.resize_display = "no"

        def calculate_workarea(*_args) -> None:
            pass

        def set_desktop_geometry(*_args) -> None:
            pass

        def make_display_manager():
            dm = DisplayManager()
            dm.calculate_workarea = calculate_workarea
            dm.set_desktop_geometry = set_desktop_geometry
            return dm
        self._test_mixin_class(make_display_manager, opts, {}, DisplayConnection)


class ConfigureDisplayTest(unittest.TestCase):

    def test_dpi_is_applied_before_resizing(self):
        # the new DPI is used for the physical dimensions of the resized display
        from unittest.mock import Mock
        from xpra.net.common import Packet
        from xpra.server.subsystem.display import DisplayManager
        dm = DisplayManager()
        ss = Mock()
        ss.screen_sizes = ()
        dm.get_server_source = lambda _proto: ss
        dm.calculate_workarea = Mock()
        dm.set_desktop_geometry_attributes = Mock()
        dm.apply_refresh_rate = Mock()
        dm.dpi_changed = Mock()
        dpi_used = []
        dm.set_screen_size = lambda *_args: dpi_used.append((dm.xdpi, dm.ydpi))
        dm._process_display_configure(None, Packet("configure-display", {
            "desktop-size": (1920, 1080),
            "dpi": {"x": 120, "y": 144},
        }))
        self.assertEqual(dpi_used, [(120, 144)])
        self.assertEqual(dm.dpi, 132)
        dm.dpi_changed.assert_called_once_with()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
