#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from xpra.os_util import POSIX
from xpra.util.io import (
    load_binary_file,
    filedata_nocrlf,
    is_socket,
    umask_context,
    find_in_PATH,
    which,
    get_status_output,
    get_proc_cmdline,
    path_permission_info,
    find_lib,
    osclose,
)


class TestLoadBinaryFile(unittest.TestCase):

    def test_reads_content(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            path = f.name
        try:
            self.assertEqual(load_binary_file(path), b"hello world")
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            self.assertEqual(load_binary_file(path), b"")
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_binary_file("/nonexistent/path/file.bin"), b"")

    def test_empty_path_returns_empty(self):
        self.assertEqual(load_binary_file(""), b"")

    def test_none_path_returns_empty(self):
        self.assertEqual(load_binary_file(None), b"")

    def test_binary_content(self):
        data = bytes(range(256))
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertEqual(load_binary_file(path), data)
        finally:
            os.unlink(path)


class TestFiledataNocrlf(unittest.TestCase):

    def test_strips_trailing_newline(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content\n")
            path = f.name
        try:
            self.assertEqual(filedata_nocrlf(path), b"content")
        finally:
            os.unlink(path)

    def test_strips_crlf(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content\r\n")
            path = f.name
        try:
            self.assertEqual(filedata_nocrlf(path), b"content")
        finally:
            os.unlink(path)

    def test_strips_both_ends(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\n\rcontent\r\n")
            path = f.name
        try:
            self.assertEqual(filedata_nocrlf(path), b"content")
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self):
        self.assertEqual(filedata_nocrlf("/nonexistent/path/file"), b"")


class TestIsSocket(unittest.TestCase):

    @unittest.skipUnless(POSIX, "Unix sockets only on POSIX")
    def test_detects_socket(self):
        import socket
        with tempfile.TemporaryDirectory() as d:
            sockpath = os.path.join(d, "test.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.bind(sockpath)
                self.assertTrue(is_socket(sockpath))
            finally:
                s.close()

    def test_regular_file_is_not_socket(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            self.assertFalse(is_socket(path))
        finally:
            os.unlink(path)

    def test_nonexistent_path_is_not_socket(self):
        self.assertFalse(is_socket("/nonexistent/path/sock"))

    @unittest.skipUnless(POSIX, "uid check only on POSIX")
    def test_uid_check_matches(self):
        import socket
        with tempfile.TemporaryDirectory() as d:
            sockpath = os.path.join(d, "test.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.bind(sockpath)
                self.assertTrue(is_socket(sockpath, check_uid=os.getuid()))
            finally:
                s.close()

    @unittest.skipUnless(POSIX, "uid check only on POSIX")
    def test_uid_check_mismatch(self):
        import socket
        with tempfile.TemporaryDirectory() as d:
            sockpath = os.path.join(d, "test.sock")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.bind(sockpath)
                # uid 0 (root) won't match unless we are root
                if os.getuid() != 0:
                    self.assertFalse(is_socket(sockpath, check_uid=0))
            finally:
                s.close()


class TestUmaskContext(unittest.TestCase):

    def test_restores_umask(self):
        original = os.umask(0o022)
        os.umask(original)   # restore immediately to learn the current umask
        with umask_context(0o077):
            self.assertEqual(os.umask(0o077), 0o077)   # read & restore inside context
        # after exiting, umask should be original again
        restored = os.umask(original)
        os.umask(restored)
        self.assertEqual(restored, original)

    def test_repr(self):
        ctx = umask_context(0o022)
        self.assertIn("umask_context", repr(ctx))

    def test_sets_requested_umask(self):
        with umask_context(0o077):
            current = os.umask(0o077)
            os.umask(current)
            self.assertEqual(current, 0o077)


class TestFindInPATH(unittest.TestCase):

    def test_finds_existing_command(self):
        result = find_in_PATH("python3")
        if result is not None:
            self.assertTrue(os.path.isfile(result))

    def test_missing_command_returns_none(self):
        result = find_in_PATH("__xpra_nonexistent_command__")
        self.assertIsNone(result)

    def test_empty_path_env(self):
        from xpra.util.env import OSEnvContext
        with OSEnvContext():
            os.environ.pop("PATH", None)
            result = find_in_PATH("python3")
            self.assertIsNone(result)


class TestWhich(unittest.TestCase):

    def test_finds_python3(self):
        result = which("python3")
        self.assertIsInstance(result, str)
        if result:
            self.assertTrue(os.path.isfile(result))

    def test_missing_command_returns_empty_string(self):
        result = which("__xpra_nonexistent_command__")
        self.assertEqual(result, "")

    def test_always_returns_string(self):
        result = which("python3")
        self.assertIsInstance(result, str)


class TestProcessAndPathHelpers(unittest.TestCase):

    def test_status_output(self):
        self.assertEqual(get_status_output(("sh", "-c", "printf out; printf err >&2; exit 3")), (3, "out", "err"))
        with patch("subprocess.Popen", side_effect=OSError("bad")):
            self.assertEqual(get_status_output(("missing",)), (-1, "", ""))

    def test_proc_cmdline(self):
        with patch("xpra.util.io.os.path.exists", return_value=True), \
                patch("xpra.util.io.load_binary_file", return_value=b"python\0script.py\0"):
            self.assertEqual(get_proc_cmdline(123), ("python", "script.py"))
        self.assertEqual(get_proc_cmdline(0), ())

    def test_permission_info_and_library_lookup(self):
        with tempfile.NamedTemporaryFile() as filename:
            info = path_permission_info(filename.name)
            self.assertEqual(len(info), 2)
            self.assertIn("permissions", info[0])
        self.assertIn("failed to query", path_permission_info("/missing")[0])
        with tempfile.TemporaryDirectory() as directory:
            library = os.path.join(directory, "libtest.so")
            open(library, "wb").close()
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": directory}):
                self.assertEqual(find_lib("libtest.so"), library)

    def test_osclose(self):
        rfd, wfd = os.pipe()
        osclose(rfd, wfd, 0)
        for fd in (rfd, wfd):
            with self.assertRaises(OSError):
                os.fstat(fd)
        logger = Mock()
        with patch("xpra.util.io.get_util_logger", return_value=logger):
            osclose(rfd)
        logger.error.assert_called_once()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
