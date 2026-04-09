#!/usr/bin/env python3
# ABOUTME: Tests for OpenGL renderer eligibility checks in can_use_opengl().
# ABOUTME: Covers opaque-region-based alpha override on Win32.
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch, MagicMock

from xpra.util.objects import typedict

# GTKXpraClient import triggers X11 display init, so skip if no display
GTKXpraClient = None
try:
    from xpra.client.gtk3.client_base import GTKXpraClient
except Exception:
    pass


def _can_use_opengl(w, h, metadata, override_redirect=False, xscale=1, yscale=1):
    """Call can_use_opengl() with a mock self to avoid GTK initialization.

    Uses opengl_force=True to skip texture/size/window-type checks
    and isolate the Win32 alpha+opaque-region logic.
    """
    client = MagicMock()
    client.GLClientWindowClass = MagicMock()
    client.opengl_enabled = True
    client.opengl_force = True
    client.headerbar = "no"
    client.sx = lambda v: round(v * xscale)
    client.sy = lambda v: round(v * yscale)
    return GTKXpraClient.can_use_opengl(client, w, h, metadata, override_redirect)


@unittest.skipIf(GTKXpraClient is None, "no display available")
class TestCanUseOpenGLWin32Alpha(unittest.TestCase):
    """Test that can_use_opengl() allows OpenGL on Win32 when opaque-region covers the window."""

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_has_alpha_blocks_opengl_on_win32(self):
        # Baseline: has-alpha=True without opaque-region → no OpenGL on Win32
        metadata = typedict({"has-alpha": True, "decorations": True})
        self.assertFalse(_can_use_opengl(1920, 1080, metadata))

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_opaque_region_allows_opengl_on_win32(self):
        # has-alpha=True but opaque-region covers full window → allow OpenGL
        metadata = typedict({
            "has-alpha": True,
            "opaque-region": ((0, 0, 1920, 1080),),
            "decorations": True,
        })
        self.assertTrue(_can_use_opengl(1920, 1080, metadata))

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_partial_opaque_region_still_blocks_opengl(self):
        # has-alpha=True with opaque-region that doesn't cover full window → no OpenGL
        metadata = typedict({
            "has-alpha": True,
            "opaque-region": ((0, 0, 960, 1080),),
            "decorations": True,
        })
        self.assertFalse(_can_use_opengl(1920, 1080, metadata))

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_no_alpha_still_allows_opengl(self):
        # has-alpha=False → OpenGL allowed regardless of opaque-region
        metadata = typedict({"has-alpha": False, "decorations": True})
        self.assertTrue(_can_use_opengl(1920, 1080, metadata))

    @patch("xpra.client.gtk3.client_base.WIN32", False)
    def test_non_win32_ignores_alpha_for_opengl(self):
        # On non-Win32, has-alpha doesn't affect OpenGL eligibility
        metadata = typedict({"has-alpha": True, "decorations": True})
        self.assertTrue(_can_use_opengl(1920, 1080, metadata))

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_opaque_region_with_desktop_scaling(self):
        # opaque-region is in server coords (1396x1022), but w/h are
        # client-scaled (2234x1635 at 1.6x). The code scales opaque-region
        # up to client space so the comparison works.
        metadata = typedict({
            "has-alpha": True,
            "opaque-region": ((0, 0, 1396, 1022),),
            "decorations": True,
        })
        scale = 1.6
        # client-scaled dimensions (same as what process_new_common computes)
        cw, ch = round(1396 * scale), round(1022 * scale)
        self.assertTrue(_can_use_opengl(cw, ch, metadata, xscale=scale, yscale=scale))

    @patch("xpra.client.gtk3.client_base.WIN32", True)
    def test_partial_opaque_region_with_desktop_scaling(self):
        # opaque-region doesn't cover full server window, still fails with scaling
        metadata = typedict({
            "has-alpha": True,
            "opaque-region": ((0, 0, 698, 1022),),
            "decorations": True,
        })
        scale = 1.6
        cw, ch = round(1396 * scale), round(1022 * scale)
        self.assertFalse(_can_use_opengl(cw, ch, metadata, xscale=scale, yscale=scale))


if __name__ == "__main__":
    unittest.main()
