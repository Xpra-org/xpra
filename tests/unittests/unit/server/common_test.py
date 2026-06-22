#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.compression import Compressed
from xpra.server import common


class ServerCommonTest(unittest.TestCase):

    def test_source_and_bandwidth_delegation(self):
        self.assertEqual(common.get_sources_by_type(object()), ())
        server = SimpleNamespace(get_sources_by_type=Mock(return_value=(1, 2)), update_bandwidth_limits=Mock())
        self.assertEqual(common.get_sources_by_type(server, str, "excluded"), (1, 2))
        server.get_sources_by_type.assert_called_once_with(str, "excluded")
        common.may_update_bandwidth_limits(server)
        server.update_bandwidth_limits.assert_called_once()
        common.may_update_bandwidth_limits(object())

    def test_session_icon_lookup(self):
        self.assertEqual(common.find_session_icon_filename(SimpleNamespace(session_name="")), "")
        with patch("xpra.platform.posix.menu_helper.find_icon", return_value="/icon.png"):
            self.assertEqual(common.find_session_icon_filename(SimpleNamespace(session_name="Xpra")), "/icon.png")

    def test_make_icon_packet(self):
        with tempfile.NamedTemporaryFile() as icon_file:
            icon_file.write(b"image")
            icon_file.flush()
            image = SimpleNamespace(size=(16, 8))
            with patch("xpra.codecs.pillow.decoder.open_only", return_value=image), \
                    patch("xpra.codecs.image.to_png", return_value=b"png-data"):
                packet = common.make_icon_packet("missing", icon_file.name)
        self.assertEqual(packet[1:5], (16, 8, "png", 64))
        self.assertIsInstance(packet[5], Compressed)
        self.assertEqual(packet[5].data, b"png-data")

    def test_make_icon_packet_failure(self):
        with patch("xpra.platform.paths.get_icon_filename", return_value="/missing"):
            with self.assertRaises(RuntimeError):
                common.make_icon_packet("missing", "")


if __name__ == "__main__":
    unittest.main()
