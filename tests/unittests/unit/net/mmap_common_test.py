#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import patch

from xpra.net.mmap import common


class MmapCommonTest(unittest.TestCase):

    def test_size_boundaries(self):
        minimum = 64 * 1024 * 1024
        maximum = 16 * 1024 * 1024 * 1024
        common.validate_size(minimum)
        common.validate_size(maximum)
        with self.assertRaisesRegex(ValueError, "minimum is 64MB"):
            common.validate_size(minimum - 1)
        with self.assertRaisesRegex(ValueError, "maximum is 16GB"):
            common.validate_size(maximum + 1)

    def test_socket_and_xpra_groups(self):
        with tempfile.NamedTemporaryFile() as socket_file:
            self.assertEqual(common.get_socket_group(socket_file.name), os.stat(socket_file.name).st_gid)
        self.assertEqual(common.get_socket_group("/missing"), -1)
        with patch.object(common, "POSIX", True), patch.object(common.os, "getgroups", return_value=[100]), \
                patch.object(common, "get_group_id", return_value=100):
            self.assertEqual(common.xpra_group(), 100)
        with patch.object(common, "POSIX", False):
            self.assertEqual(common.xpra_group(), 0)

    def test_mmap_directory_expansion_and_creation(self):
        with tempfile.TemporaryDirectory() as parent:
            target = os.path.join(parent, "mmap-$PID")
            with patch("xpra.platform.paths.get_mmap_dir", return_value=target):
                result = common.get_mmap_dir()
            self.assertTrue(os.path.isdir(result))
            self.assertIn(str(os.getpid()), result)
        with patch("xpra.platform.paths.get_mmap_dir", return_value=""):
            with self.assertRaises(RuntimeError):
                common.get_mmap_dir()


if __name__ == "__main__":
    unittest.main()
