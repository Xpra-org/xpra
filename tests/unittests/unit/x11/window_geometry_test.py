#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Hamid Taheri <taheri.hamid@gmail.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from xpra.os_util import POSIX
from xpra.util.env import OSEnvContext
from unit.server_test_util import ServerTestUtil

XID = 0x200001
CORRAL_XID = 0x200002


@unittest.skipUnless(POSIX, "X11 only")
class WindowGeometryTest(ServerTestUtil):

    @classmethod
    def setUpClass(cls):
        ServerTestUtil.setUpClass()
        cls.stack = ExitStack()
        cls.display = cls.find_free_display()
        cls.xvfb = cls.start_Xvfb(cls.display)
        cls.stack.enter_context(OSEnvContext())
        os.environ["DISPLAY"] = cls.display
        from xpra.x11.bindings.display_source import X11DisplayContext
        cls.stack.enter_context(X11DisplayContext(cls.display))
        from xpra.x11.bindings.loop import EventLoop
        cls.event_loop = EventLoop()

    def setUp(self):
        super().setUp()
        os.environ["DISPLAY"] = self.display

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.xvfb.terminate()

    def test_withdrawn_configure_request(self) -> None:
        from xpra.x11 import wm
        wm_stub = SimpleNamespace(_windows={})
        event = SimpleNamespace(window=XID, value_mask=wm.CWWidth | wm.CWHeight, x=0, y=0, width=499, height=316)
        x11 = Mock()

        def configure_request(geometry) -> None:
            x11.reset_mock()
            x11.getGeometry.return_value = geometry
            with patch.object(wm, "X11Window", x11):
                wm.Wm.do_x11_child_configure_request_event(wm_stub, event)
            x11.configure.assert_called_once_with(XID, 0, 0, 499, 316, event.value_mask)

        # the X server sends the client a real ConfigureNotify for the new size,
        # a synthetic one would arrive after it, possibly after the client's next request:
        configure_request((0, 0, 1, 1, 0, 24))
        x11.sendConfigureNotify.assert_not_called()
        # a request that changes nothing must get a synthetic ConfigureNotify (ICCCM 4.1.5):
        configure_request((0, 0, 499, 316, 0, 24))
        x11.sendConfigureNotify.assert_called_once_with(XID)

    def test_managed_configure_request(self) -> None:
        from xpra.x11.models import window
        props = {
            "geometry": (200, 300, 400, 200),
            "requested-position": (200, 300),
            "requested-size": (400, 200),
            "size-constraints": {},
        }
        model = SimpleNamespace(
            xid=XID, corral_xid=CORRAL_XID, emit=Mock(),
            get_property=props.get,
            _internal_set_property=props.__setitem__,
        )

        def updateprop(name, value) -> bool:
            changed = props[name] != value
            props[name] = value
            return changed

        model._updateprop = updateprop
        x11 = Mock()

        def configure_request(mask, x=0, y=0, width=1, height=1):
            x11.reset_mock()
            event = SimpleNamespace(value_mask=mask, x=x, y=y, width=width, height=height)
            with patch.object(window, "X11Window", x11):
                window.WindowModel.do_x11_child_configure_request_event(model, event)
            return x11.method_calls

        # the position is applied to the corral, never to the reparented client window,
        # and the axes that were not requested are preserved:
        self.assertEqual(configure_request(window.CWX, x=240), [
            call.MoveWindow(CORRAL_XID, 240, 300),
            call.sendConfigureNotify(XID),
        ])
        self.assertEqual(configure_request(window.CWY, y=0), [
            call.MoveWindow(CORRAL_XID, 240, 0),
            call.sendConfigureNotify(XID),
        ])
        self.assertEqual(configure_request(window.CWWidth, width=500), [
            call.ResizeWindow(CORRAL_XID, 500, 200),
            call.ResizeWindow(XID, 500, 200),
        ])
        self.assertEqual(configure_request(window.CONFIGURE_GEOMETRY_MASK, -20, 10, 300, 100), [
            call.MoveResizeWindow(CORRAL_XID, -20, 10, 300, 100),
            call.ResizeWindow(XID, 300, 100),
        ])
        self.assertEqual(props["geometry"], (-20, 10, 300, 100))
        # nothing changed: only a synthetic ConfigureNotify (ICCCM 4.1.5)
        self.assertEqual(configure_request(window.CWX, x=-20), [call.sendConfigureNotify(XID)])


def main():
    unittest.main()


if __name__ == '__main__':
    main()
