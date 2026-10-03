#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import importlib.util
import unittest
from contextlib import suppress
from unittest.mock import Mock, patch

from xpra.os_util import OSX, POSIX
from unit.process_test_util import DisplayContext


@unittest.skipUnless(importlib.util.find_spec("xpra.x11.bindings.window"), "X11 bindings are not built")
class SeamlessWindowTest(unittest.TestCase):

    def test_lost_active_window(self) -> None:
        # the X11 server module needs a display to load its bindings:
        with DisplayContext():
            import gi
            gi.require_version("Gdk", "3.0")  # @UndefinedVariable
            gi.require_version("Gtk", "3.0")  # @UndefinedVariable
            gi.require_version("GdkX11", "3.0")  # @UndefinedVariable
            from xpra.x11 import server
            self.do_test_lost_active_window(server)

    def do_test_lost_active_window(self, server_module) -> None:
        XpraServer = server_module.XpraServer

        class Window:
            def __init__(self, xid: int):
                self.xid = xid

        class ServerStub:
            def __init__(self):
                self._id_to_window = {1: Window(101), 2: Window(102), 3: Window(103)}
                self._window_to_id = {window: wid for wid, window in self._id_to_window.items()}
                self._has_focus = 1
                self._exit_with_windows = False
                self.cancel_configure_damage = Mock()
                self.repaint_root_overlay = Mock()

            def reset_focus(self):
                pass

            def restore_active_window(self, window):
                XpraServer.restore_active_window(self, window)

            def _remove_window(self, window):
                wid = self._window_to_id.pop(window)
                del self._id_to_window[wid]
                return wid

        server = ServerStub()
        active = [102]

        def set_active(_xid, _name, _type, xid):
            active[0] = xid

        with patch.object(server_module, "xswallow", suppress()), \
                patch.object(server_module, "prop_get", return_value=active[0]) as get_active, \
                patch.object(server_module, "prop_set", side_effect=set_active) as set_active_mock:
            # the active window goes away, give it back to the window which has the focus:
            XpraServer._lost_window(server, server._id_to_window[2])
            self.assertEqual(active[0], 101)
            self.assertEqual(server._has_focus, 1)
            set_active_mock.assert_called_once()
            self.assertEqual(set_active_mock.call_args[0][1:], ("_NET_ACTIVE_WINDOW", "u32", 101))

            # a window which is not the active one goes away, nothing to do:
            get_active.return_value = active[0]
            XpraServer._lost_window(server, server._id_to_window[3])
            self.assertEqual(active[0], 101)
            set_active_mock.assert_called_once()

            # the focused window goes away:
            XpraServer._lost_window(server, server._id_to_window[1])
            self.assertEqual(server._has_focus, 0)
            self.assertEqual(active[0], server_module.XNone)


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
