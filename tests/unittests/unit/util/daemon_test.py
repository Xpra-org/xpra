#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.os_util import POSIX


class TestSelectLogFile(unittest.TestCase):

    def test_absolute_log_file(self):
        from xpra.util.daemon import select_log_file
        result = select_log_file("/tmp", "/var/log/xpra.log", ":10")
        self.assertEqual(result, "/var/log/xpra.log")

    def test_relative_log_file_joined_with_dir(self):
        from xpra.util.daemon import select_log_file
        result = select_log_file("/tmp/logdir", "server.log", ":10")
        self.assertEqual(result, "/tmp/logdir/server.log")

    def test_display_substitution_in_log_file(self):
        from xpra.util.daemon import select_log_file
        result = select_log_file("/tmp", "xpra-$DISPLAY.log", ":7")
        self.assertIn("7", result)

    def test_no_log_file_with_display(self):
        from xpra.util.daemon import select_log_file
        result = select_log_file("/tmp", "", ":5")
        self.assertIn("5", result)
        self.assertTrue(result.endswith(".log"))

    def test_no_log_file_no_display_uses_pid(self):
        from xpra.util.daemon import select_log_file
        result = select_log_file("/tmp", "", "")
        self.assertIn(str(os.getpid()), result)
        self.assertTrue(result.endswith(".log"))


class TestOpenLogFile(unittest.TestCase):

    def test_creates_new_file(self):
        from xpra.util.daemon import open_log_file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.log")
            fd = open_log_file(path)
            self.assertGreaterEqual(fd, 0)
            os.close(fd)
            self.assertTrue(os.path.exists(path))

    def test_renames_existing_file(self):
        from xpra.util.daemon import open_log_file
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.log")
            with open(path, "w") as f:
                f.write("old content")
            fd = open_log_file(path)
            os.close(fd)
            self.assertTrue(os.path.exists(path + ".old"))

    def test_raises_on_bad_path(self):
        from xpra.util.daemon import open_log_file
        from xpra.scripts.config import InitException
        with self.assertRaises(InitException):
            open_log_file("/nonexistent/dir/test.log")


@unittest.skipUnless(POSIX, "POSIX only")
class TestSetuidgid(unittest.TestCase):

    def test_noop_same_uid_gid(self):
        from xpra.util.daemon import setuidgid
        # calling with current uid/gid should be a no-op
        setuidgid(os.getuid(), os.getgid())

    def test_invalid_uid_raises(self):
        from xpra.util.daemon import setuidgid
        with self.assertRaises((ValueError, OSError)):
            setuidgid(999999, os.getgid())


if __name__ == "__main__":
    unittest.main()
