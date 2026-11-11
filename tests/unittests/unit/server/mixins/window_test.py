#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class WebcamMixinTest(ServerMixinTest):

    def test_auto_refresh_control_uses_milliseconds(self):
        from xpra.server.mixins.controlcommands import ServerBaseControlCommands

        server = ServerBaseControlCommands()
        sources = (Mock(), Mock())
        server._ws_from_args = Mock(return_value=sources)
        for seconds, milliseconds in ((0.5, 500), ("0.15", 150), (0, 0)):
            with self.subTest(seconds=seconds):
                result = server.control_command_auto_refresh(seconds, 1, 2)
                server._ws_from_args.assert_called_with(1, 2)
                for source in sources:
                    source.set_auto_refresh_delay.assert_called_once_with(milliseconds)
                    source.reset_mock()
                self.assertEqual(result, f"auto-refresh delay set to {milliseconds}ms for windows (1, 2)")

    def test_windowserver(self):
        from xpra.server.mixins.window import WindowServer
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
