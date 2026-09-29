#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("xpra.x11.bindings.core"), "X11 bindings are not built")
class SeamlessWindowTest(unittest.TestCase):

    def test_lost_active_window(self) -> None:
        from xpra.x11.server import seamless

        class Window:
            def __init__(self, xid: int):
                self.xid = xid

        class ServerStub:
            def __init__(self):
                self.windows = {1: Window(101), 2: Window(102), 3: Window(103)}
                self._window_to_id = {window: wid for wid, window in self.windows.items()}
                self._has_focus = 1
                self._exit_with_windows = False
                self.cancel_configure_damage = Mock()
                self.repaint_root_overlay = Mock()

            def get_window(self, wid):
                return self.windows.get(wid)

            def reset_focus(self):
                self._has_focus = 0

            def restore_active_window(self, window):
                seamless.SeamlessServer.restore_active_window(self, window)

            def _remove_window(self, window):
                wid = self._window_to_id.pop(window)
                del self.windows[wid]
                return wid

        server = ServerStub()
        active = [102]

        def set_active(_name, _type, xid):
            active[0] = xid

        with patch.object(seamless, "xswallow", nullcontext()), \
                patch.object(seamless, "root_get", return_value=active[0]) as get_active, \
                patch.object(seamless, "root_set", side_effect=set_active) as set_active_mock:
            seamless.SeamlessServer._lost_window(server, server.windows[2])
            self.assertEqual(active[0], 101)
            self.assertEqual(server._has_focus, 1)
            set_active_mock.assert_called_once_with("_NET_ACTIVE_WINDOW", "u32", 101)

            get_active.return_value = active[0]
            seamless.SeamlessServer._lost_window(server, server.windows[3])
            self.assertEqual(active[0], 101)
            set_active_mock.assert_called_once()

            seamless.SeamlessServer._lost_window(server, server.windows[1])
            self.assertEqual(server._has_focus, 0)
            self.assertEqual(active[0], seamless.XNone)


if __name__ == "__main__":
    unittest.main()
