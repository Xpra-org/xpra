#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from xpra.server.window.window_source import WindowSource
from xpra.util import typedict


class WindowSourceTest(unittest.TestCase):

    @staticmethod
    def make_source():
        source = object.__new__(WindowSource)
        source.init_vars()
        source.client_render_size = None
        source.client_bit_depth = 24
        source.send_window_size = False
        source._all_encoders = {}
        source._encoders = {}
        source.update_encoding_selection = Mock()
        return source

    def test_client_properties_preserve_render_size(self):
        # The client only sends the properties that have changed.
        source = self.make_source()
        source.do_set_client_properties(typedict({"encoding.render-size": (640, 480)}))
        self.assertEqual(source.client_render_size, (640, 480))
        source.do_set_client_properties(typedict({"encoding.transparency": False}))
        self.assertEqual(source.client_render_size, (640, 480))
        source.do_set_client_properties(typedict({"encoding.render-size": (800, 600)}))
        self.assertEqual(source.client_render_size, (800, 600))

    def test_maximized_follows_window(self):
        source = self.make_source()
        source.window = SimpleNamespace(get_property=Mock())
        source.reconfigure = Mock()
        for maximized in (True, False):
            with self.subTest(maximized=maximized):
                source.window.get_property.return_value = maximized
                self.assertTrue(source._maximized_changed(source.window))
                self.assertEqual(source.maximized, maximized)
                source.reconfigure.assert_called_once_with(True)
                source.reconfigure.reset_mock()
                source.do_set_client_properties(typedict({"encoding.transparency": False}))
                self.assertEqual(source.maximized, maximized)
                source.do_set_client_properties(typedict({"maximized": not maximized}))
                self.assertEqual(source.maximized, maximized)


if __name__ == '__main__':
    unittest.main()
