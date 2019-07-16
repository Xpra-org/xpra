#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class WebcamMixinTest(ServerMixinTest):

    def test_windowserver(self):
        from xpra.server.mixins.window_server import WindowServer
        opts = AdHocStruct()
        opts.min_size = "10x10"
        opts.max_size = "16384x8192"
        def load_existing_windows():
            pass
        def _WindowServer():
            ws = WindowServer()
            ws.load_existing_windows = load_existing_windows
            return ws
        self._test_mixin_class(_WindowServer, opts)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
