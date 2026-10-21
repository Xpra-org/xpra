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


class ManagedGeometryStub:
    """Exercise the real request/application methods without a GObject instance."""

    xid = XID
    corral_xid = CORRAL_XID

    def __init__(self, geometry=(200, 300, 413, 229), hints=None):
        self.properties = {
            "geometry": geometry,
            "requested-position": geometry[:2],
            "requested-size": geometry[2:],
            "size-constraints": hints or {},
        }
        self.emit = Mock()

    def get_property(self, name):
        return self.properties[name]

    def _internal_set_property(self, name, value):
        self.properties[name] = value

    def _updateprop(self, name, value):
        changed = self.properties.get(name) != value
        self.properties[name] = value
        return changed

    @staticmethod
    def calc_constrained_size(w, h, hints):
        from xpra.x11.models.window import calc_constrained_size
        return calc_constrained_size(w, h, hints)

    def _do_update_client_geometry(self, *geometry):
        from xpra.x11.models.window import WindowModel
        WindowModel._do_update_client_geometry(self, *geometry)


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

    def test_managed_partial_requests_preserve_root_axes(self) -> None:
        from xpra.x11.models import window
        model = ManagedGeometryStub()
        x11 = Mock()
        for mask, requested, expected in (
                (window.CWX, (240, 0, 1, 1), (240, 300, 413, 229)),
                (window.CWY, (0, 350, 1, 1), (240, 350, 413, 229)),
                (window.CWX, (280, 0, 1, 1), (280, 350, 413, 229)),
                (window.CWWidth, (0, 0, 500, 1), (280, 350, 500, 229)),
                (window.CWHeight, (0, 0, 1, 270), (280, 350, 500, 270)),
                (window.CWX | window.CWY, (0, 0, 1, 1), (0, 0, 500, 270)),
                (window.CWX | window.CWY, (-150, -20, 1, 1), (-150, -20, 500, 270)),
        ):
            with self.subTest(mask=mask, target=expected):
                x11.reset_mock()
                x11.getGeometry.return_value = model.get_property("geometry")
                event = SimpleNamespace(value_mask=mask, x=requested[0], y=requested[1],
                                        width=requested[2], height=requested[3])
                with patch.object(window, "X11Window", x11):
                    window.WindowModel.do_x11_child_configure_request_event(model, event)
                self.assertEqual(model.get_property("geometry"), expected)
                x11.MoveResizeWindow.assert_called_once_with(CORRAL_XID, *expected)
                x11.configure.assert_called_once_with(XID, 0, 0, *expected[2:])
                x11.sendConfigureNotify.assert_called_once_with(XID)

    def test_managed_request_constraints_and_notifications(self) -> None:
        from xpra.x11.models import window
        model = ManagedGeometryStub(hints={"minimum-size": (100, 80), "maximum-size": (500, 400)})
        x11 = Mock()
        x11.getGeometry.return_value = model.get_property("geometry")
        event = SimpleNamespace(value_mask=window.CONFIGURE_GEOMETRY_MASK, x=250, y=360, width=800, height=20)
        with patch.object(window, "X11Window", x11):
            window.WindowModel.do_x11_child_configure_request_event(model, event)
        self.assertEqual(model.get_property("geometry"), (250, 360, 500, 80))
        self.assertEqual(x11.method_calls, [
            call.getGeometry(CORRAL_XID),
            call.MoveResizeWindow(CORRAL_XID, 250, 360, 500, 80),
            call.configure(XID, 0, 0, 500, 80),
            call.sendConfigureNotify(XID),
        ])
        # Even no-op/restack-only requests must acknowledge actual geometry,
        # normalizing the child origin without interpreting zero as a move.
        for mask in (0, window.CWStackMode):
            x11.reset_mock()
            x11.getGeometry.return_value = model.get_property("geometry")
            event.value_mask = mask
            event.detail = 0
            event.above = 0
            with patch.object(window, "X11Window", x11):
                window.WindowModel.do_x11_child_configure_request_event(model, event)
            x11.MoveResizeWindow.assert_not_called()
            x11.configure.assert_called_once_with(XID, 0, 0, 500, 80)
            x11.sendConfigureNotify.assert_called_once_with(XID)
            self.assertEqual(model.get_property("geometry"), (250, 360, 500, 80))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
