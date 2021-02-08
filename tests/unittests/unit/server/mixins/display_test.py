#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class DisplayMixinTest(ServerMixinTest):

    def test_display(self):
        with DisplayContext():
            self.do_test_display()

    def do_test_display(self):
        from xpra.server.mixins.display_manager import DisplayManager
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        opts = AdHocStruct()
        opts.bell = True
        opts.cursors = True
        opts.dpi = 144
        opts.opengl = "no"
        def get_root_window_size():
            return 1024, 768
        def calculate_workarea(*_args):
            pass
        def set_desktop_geometry(*_args):
            pass
        def _DisplayManager():
            dm = DisplayManager()
            dm.get_root_window_size = get_root_window_size
            dm.calculate_workarea = calculate_workarea
            dm.set_desktop_geometry = set_desktop_geometry
            return dm
        self._test_mixin_class(_DisplayManager, opts, {}, ClientDisplayMixin)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
