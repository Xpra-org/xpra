#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util import AdHocStruct
from xpra.os_util import POSIX, OSX
from unit.server.mixins.servermixintest_util import ServerMixinTest


class DisplayMixinTest(ServerMixinTest):

    def test_display(self):
        if os.environ.get("DISPLAY") and POSIX and not OSX and os.environ.get("GDK_BACKEND", "x11")=="x11":
            from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
            init_gdk_display_source()
        from xpra.server.mixins.display_manager import DisplayManager
        from xpra.server.source.clientdisplay_mixin import ClientDisplayMixin
        opts = AdHocStruct()
        opts.bell = True
        opts.cursors = True
        opts.dpi = 144
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
