#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.net.common import Packet
from xpra.util.objects import AdHocStruct
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class WebcamMixinTest(ServerMixinTest):
    def test_legacy_configure_accepts_negative_resize_counter(self):
        from xpra.server.subsystem.window import WindowServer

        window_server = WindowServer.__new__(WindowServer)
        window = Mock()
        window.is_OR.return_value = False
        window_server.get_window = Mock(return_value=window)
        window_server.do_process_window_configure = Mock()
        packet = Packet("configure-window", 1, 2, 3, 4, 5, {}, -1)
        window_server._process_configure_window(object(), packet)
        config = window_server.do_process_window_configure.call_args.args[2]
        self.assertEqual(config.intget("resize-counter"), -1)

    def test_windowserver(self):
        from xpra.server.subsystem.window import WindowServer

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


if __name__ == "__main__":
    main()
