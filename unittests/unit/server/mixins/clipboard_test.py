#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from xpra.os_util import POSIX, OSX
from unit.server.mixins.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class ClipboardMixinTest(ServerMixinTest):

    def test_clipboard(self):
        with DisplayContext():
            if POSIX and not OSX:
                from xpra.x11.gtk_x11.gdk_display_source import init_gdk_display_source
                init_gdk_display_source()
            from xpra.server.mixins.clipboard_server import ClipboardServer
            from xpra.server.source.clipboard_connection import ClipboardConnection
            opts = AdHocStruct()
            opts.clipboard = "yes"
            opts.clipboard_direction = "both"
            opts.clipboard_filter_file = None
            self._test_mixin_class(ClipboardServer, opts, {}, ClipboardConnection)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
