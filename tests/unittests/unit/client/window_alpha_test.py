#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.gui import client_window_base as window_base
from xpra.common import noop
from xpra.util import typedict


class Window(window_base.ClientWindowBase):

    def set_decorated(self, decorated: bool) -> None:
        pass

    def setup_window(self, bw: int, bh: int) -> None:
        self.initial_alpha = self._has_alpha

    def set_opaque_region(self, opaque_region) -> None:
        pass


class WindowAlphaTest(unittest.TestCase):

    def make_window(self, metadata=None, geom=(0, 0, 64, 32), backing_size=(64, 32)):
        client = SimpleNamespace(
            readonly=False, xscale=geom[2] / backing_size[0], yscale=geom[3] / backing_size[1],
            source_remove=noop, idle_add=noop, timeout_add=noop,
        )
        md = typedict({"has-alpha": True})
        md.update(metadata or {})
        return Window(client, None, 0, 1, *geom, *backing_size, md, False, typedict(), None, (), None, 0)

    @patch.object(window_base, "OSX", True)
    def test_opaque_region_drops_alpha(self):
        # #5120: drop alpha before window setup, and keep it disabled when applying metadata.
        window = self.make_window({"opaque-region": ((0, 0, 64, 32), )})
        self.assertFalse(window.initial_alpha)
        self.assertFalse(window._has_alpha)
        window.update_metadata(typedict({"has-alpha": True}))
        self.assertFalse(window._has_alpha)

    @patch.object(window_base, "OSX", True)
    def test_partial_opaque_region_keeps_alpha(self):
        window = self.make_window({"opaque-region": ((0, 0, 64, 16), )})
        self.assertTrue(window.initial_alpha)
        self.assertTrue(window._has_alpha)

    @patch.object(window_base, "OSX", True)
    def test_missing_opaque_region_keeps_alpha(self):
        window = self.make_window()
        self.assertTrue(window.initial_alpha)
        self.assertTrue(window._has_alpha)

    @patch.object(window_base, "OSX", False)
    def test_other_platforms_keep_alpha(self):
        window = self.make_window({"opaque-region": ((0, 0, 64, 32), )})
        self.assertTrue(window.initial_alpha)
        self.assertTrue(window._has_alpha)

    @patch.object(window_base, "OSX", True)
    def test_opaque_region_uses_backing_size(self):
        window = self.make_window({"opaque-region": ((0, 0, 64, 32), )}, geom=(0, 0, 128, 64))
        self.assertFalse(window.initial_alpha)
        self.assertFalse(window._has_alpha)

    @patch.object(window_base, "OSX", True)
    def test_opaque_region_must_cover_backing(self):
        window = self.make_window({"opaque-region": ((0, 0, 32, 16), )}, geom=(0, 0, 32, 16))
        self.assertTrue(window.initial_alpha)
        self.assertTrue(window._has_alpha)

    @patch.object(window_base, "OSX", True)
    def test_no_alpha_stays_disabled(self):
        window = self.make_window({"has-alpha": False, "opaque-region": ((0, 0, 64, 32), )})
        self.assertFalse(window.initial_alpha)
        self.assertFalse(window._has_alpha)


if __name__ == "__main__":
    unittest.main()
