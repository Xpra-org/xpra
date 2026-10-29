#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import patch


class XTestPointerWarpTest(unittest.TestCase):

    @patch("xpra.x11.server.xtest_pointer._warp_pointer", return_value=True)
    @patch("xpra.x11.server.xtest_pointer.XTestBindings")
    def test_move_pointer_warps_before_xtest_fallback(self, bindings, warp):
        from xpra.x11.server.xtest_pointer import XTestPointerDevice

        XTestPointerDevice.move_pointer(42, 84, {})
        warp.assert_called_once_with(42, 84)
        bindings.return_value.xtest_fake_motion.assert_not_called()

    @patch("xpra.x11.server.xtest_pointer._warp_pointer", return_value=False)
    @patch("xpra.x11.server.xtest_pointer.XTestBindings")
    def test_move_pointer_falls_back_when_warp_fails(self, bindings, warp):
        from xpra.x11.server.xtest_pointer import XTestPointerDevice

        XTestPointerDevice.move_pointer(10, 20, {})
        warp.assert_called_once_with(10, 20)
        bindings.return_value.xtest_fake_motion.assert_called_once_with(10, 20)


if __name__ == "__main__":
    unittest.main()
