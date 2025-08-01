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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
