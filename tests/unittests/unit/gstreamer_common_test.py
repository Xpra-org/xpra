#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.gstreamer import common


class TestGStreamerCommon(unittest.TestCase):

    def test_import_gst_uses_an_empty_argv(self):
        gst = Mock()
        with patch.object(common, "Gst", None), \
                patch.object(common, "gi_import", return_value=gst):
            assert common.import_gst() is gst
        gst.init.assert_called_once_with([])

    def test_import_gst_does_not_cache_a_failed_initialization(self):
        gst = Mock()
        gst.init.side_effect = TypeError("invalid argv")
        with patch.object(common, "Gst", None), \
                patch.object(common, "gi_import", return_value=gst):
            assert common.import_gst() is None
            assert common.Gst is None


if __name__ == "__main__":
    unittest.main()
