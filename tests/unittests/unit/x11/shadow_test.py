#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from xpra.os_util import OSX, POSIX


@unittest.skipUnless(POSIX and not OSX, "X11 only")
class ShadowX11Test(unittest.TestCase):

    def setUp(self):
        self.enterContext(patch("xpra.x11.bindings.core.X11CoreBindings"))

    def test_dynamic_window_capture(self):
        from xpra.x11.shadow import server as shadow
        server = shadow.ShadowX11Server.__new__(shadow.ShadowX11Server)
        server.capture = None
        server._captures = []
        server.display_options = "windows=test"
        display = Mock()
        display.get_display_name.return_value = ":test"
        display.get_display_size.return_value = (1920, 1080)
        server.subsystems = {"display": display}
        capture = Mock()

        def match_windows(spec, model_class):
            self.assertEqual(spec, ["test"])
            return [model_class("test", (100, 200, 640, 480))]

        with patch.object(server, "setup_capture", return_value=capture) as setup, \
                patch.object(shadow, "window_matches", side_effect=match_windows):
            # The refresh path must reuse the capture without registering it twice.
            for _ in range(2):
                model, = server.make_capture_window_models()
                self.assertIs(model.capture, capture)
                self.assertEqual(model.title, "test")
                self.assertEqual(model.geometry, (100, 200, 640, 480))
                self.assertIn("size-constraints", model.dynamic_property_names)
                self.assertIs(server.capture, capture)
                self.assertEqual(server._captures, [capture])
            setup.assert_called_once_with()
        model.get_image(5, 10, 20, 30)
        capture.get_image.assert_called_once_with(105, 210, 20, 30)
        server.cleanup_capture()
        capture.clean.assert_called_once_with()

    def test_matched_window_uses_root_coordinates(self):
        from xpra.x11.shadow import filter as shadow_filter
        from xpra.x11.shadow.model import X11ShadowModel
        bindings = Mock()
        bindings.get_all_x11_windows.return_value = []
        # A client at (3, 4) inside a window manager frame at (100, 200).
        bindings.getGeometry.return_value = (3, 4, 640, 480, 0, 24)
        bindings.getParent.return_value = 0
        bindings.is_override_redirect.return_value = False

        def model_class(title, geometry):
            return X11ShadowModel(None, title, geometry)

        with patch("xpra.x11.bindings.window.X11WindowBindings", return_value=bindings), \
                patch.object(shadow_filter, "prop_get", return_value=None), \
                patch.object(shadow_filter, "xsync", nullcontext()):
            for position in ((103, 204), (0, 0), (-100, 20), None):
                with self.subTest(position=position):
                    bindings.get_absolute_position.return_value = position
                    models = list(shadow_filter.window_matches(["xid=0x123"], model_class))
                    if position is None:
                        self.assertEqual(models, [])
                    else:
                        model, = models
                        self.assertEqual(model.geometry, (*position, 640, 480))
                        self.assertEqual(model.get_id(), 0x123)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
