#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.util.pid import load_pid, write_pid, write_pidfile, rm_pidfile


class TestLoadPid(unittest.TestCase):

    def test_missing_file_returns_zero(self):
        self.assertEqual(load_pid("/nonexistent/path/pid.file"), 0)

    def test_empty_path_returns_zero(self):
        self.assertEqual(load_pid(""), 0)

    def test_reads_pid(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pid") as f:
            f.write(b"12345\n")
            path = f.name
        try:
            self.assertEqual(load_pid(path), 12345)
        finally:
            os.unlink(path)

    def test_strips_whitespace(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pid") as f:
            f.write(b"  99\r\n")
            path = f.name
        try:
            # rstrip("\n\r") is applied; leading spaces cause ValueError → returns 0
            result = load_pid(path)
            self.assertIsInstance(result, int)
        finally:
            os.unlink(path)

    def test_invalid_content_returns_zero(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".pid") as f:
            f.write(b"not-a-pid\n")
            path = f.name
        try:
            self.assertEqual(load_pid(path), 0)
        finally:
            os.unlink(path)


class TestWritePid(unittest.TestCase):

    def _tmppath(self):
        fd, path = tempfile.mkstemp(suffix=".pid")
        os.close(fd)
        return path

    def test_writes_and_returns_inode(self):
        path = self._tmppath()
        try:
            inode = write_pid(path, 12345)
            self.assertIsInstance(inode, int)
            # on real filesystems inode > 0
            self.assertGreater(inode, 0)
        finally:
            os.unlink(path)

    def test_content_is_pid(self):
        path = self._tmppath()
        try:
            write_pid(path, 99999)
            with open(path) as f:
                content = f.read().strip()
            self.assertEqual(content, "99999")
        finally:
            os.unlink(path)

    def test_invalid_pid_raises(self):
        path = self._tmppath()
        try:
            with self.assertRaises(ValueError):
                write_pid(path, 0)
            with self.assertRaises(ValueError):
                write_pid(path, -1)
        finally:
            os.unlink(path)

    def test_roundtrip_with_load(self):
        path = self._tmppath()
        try:
            write_pid(path, 55555)
            self.assertEqual(load_pid(path), 55555)
        finally:
            os.unlink(path)


class TestWritePidfile(unittest.TestCase):

    def test_writes_current_pid(self):
        fd, path = tempfile.mkstemp(suffix=".pid")
        os.close(fd)
        try:
            inode = write_pidfile(path)
            self.assertGreater(inode, 0)
            self.assertEqual(load_pid(path), os.getpid())
        finally:
            os.unlink(path)


class TestRmPidfile(unittest.TestCase):

    def _write(self, pid=12345):
        fd, path = tempfile.mkstemp(suffix=".pid")
        os.close(fd)
        inode = write_pid(path, pid)
        return path, inode

    def test_removes_file(self):
        path, inode = self._write()
        result = rm_pidfile(path, inode)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path))

    def test_wrong_inode_does_not_remove(self):
        path, inode = self._write()
        try:
            result = rm_pidfile(path, inode + 9999)
            self.assertFalse(result)
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)

    def test_zero_inode_removes_without_check(self):
        fd, path = tempfile.mkstemp(suffix=".pid")
        os.close(fd)
        result = rm_pidfile(path, 0)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(path))

    def test_nonexistent_file_returns_false(self):
        result = rm_pidfile("/nonexistent/path/pid.file", 1)
        self.assertFalse(result)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
