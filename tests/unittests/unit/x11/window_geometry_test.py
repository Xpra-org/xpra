#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import subprocess
import sys
import unittest

from xpra.os_util import OSX, POSIX
from unit.process_test_util import ProcessTestUtil


# Keep the display-bound X11 bindings in a subprocess, as in clipboard_incr_test.
CHECKS = r"""
from types import SimpleNamespace
from unittest.mock import Mock

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk
from xpra.x11.gtk3.gdk_display_source import init_gdk_display_source
init_gdk_display_source()
from xpra.gtk_common.error import xsync
from xpra.gtk_common.gtk_util import get_default_root_window
from xpra.x11.gtk_x11 import GDKX11Window
from xpra.x11.models import window

corral = GDKX11Window(get_default_root_window(), x=200, y=300, width=400, height=200)
child = GDKX11Window(corral, x=0, y=0, width=400, height=200, window_type=Gdk.WindowType.CHILD)
corral_xid, child_xid = corral.get_xid(), child.get_xid()
props = {
    "geometry": (200, 300, 400, 200),
    "requested-position": (200, 300),
    "requested-size": (400, 200),
    "size-hints": {},
}
model = SimpleNamespace(
    xid=child_xid, corral_xid=corral_xid, emit=Mock(),
    get_property=props.get, _internal_set_property=props.__setitem__,
)

def updateprop(name, value):
    changed = props[name] != value
    props[name] = value
    return changed

model._updateprop = updateprop
expected = list(props["geometry"])
try:
    for mask, values in (
        (window.CONFIGURE_GEOMETRY_MASK, (200, 300, 413, 229)),
        (window.CWX, (240, 0, 1, 1)),
        (window.CWX, (240, 0, 1, 1)),
        (window.CWY, (0, 0, 1, 1)),
        (window.CWWidth, (0, 0, 500, 1)),
        (window.CWHeight, (0, 0, 1, 270)),
        (window.CWX | window.CWY, (0, 0, 1, 1)),
        (window.CONFIGURE_GEOMETRY_MASK, (250, 200, 420, 240)),
        (window.CWX, (-30, 0, 1, 1)),
    ):
        for index, flag in enumerate((window.CWX, window.CWY, window.CWWidth, window.CWHeight)):
            if mask & flag:
                expected[index] = values[index]
        event = SimpleNamespace(value_mask=mask, x=values[0], y=values[1], width=values[2], height=values[3])
        with xsync:
            window.WindowModel.do_child_configure_request_event(model, event)
            corral_geometry = window.X11Window.getGeometry(corral_xid)[:4]
            child_geometry = window.X11Window.getGeometry(child_xid)[:4]
            absolute_position = window.X11Window.get_absolute_position(child_xid)
        assert props["geometry"] == tuple(expected), props
        assert corral_geometry == tuple(expected), (mask, corral_geometry, expected)
        assert child_geometry == (0, 0, *expected[2:]), (mask, child_geometry, expected)
        assert absolute_position == tuple(expected[:2]), (mask, absolute_position, expected)
finally:
    child.destroy()
    corral.destroy()
"""


@unittest.skipUnless(POSIX and not OSX, "X11 only")
class WindowGeometryTest(ProcessTestUtil):

    def test_managed_configure_request_coordinates(self):
        display = self.find_free_display()
        xvfb = self.start_Xvfb(display)
        try:
            env = os.environ.copy()
            env.update(DISPLAY=display, GDK_BACKEND="x11", XPRA_VALIDATE_CONFIGURE_REQUEST="0")
            proc = subprocess.run(
                (sys.executable, "-c", CHECKS),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, check=False, env=env, timeout=30,
            )
        finally:
            xvfb.terminate()
        self.assertEqual(proc.returncode, 0, f"geometry checks failed:\n{proc.stdout}\n{proc.stderr}")


if __name__ == "__main__":
    unittest.main()
