#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import stat
import sys
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.util import io
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


@unittest.skipUnless(POSIX, "Unix socket and permission helpers")
class TestSocketWaitingAndPermissions(unittest.TestCase):

    @contextmanager
    def socket_clock(self, exists=True):
        now = [10.0]
        waits = []

        def sleep(delay):
            waits.append(delay)
            now[0] += delay

        sock = Mock()
        with patch("socket.socket", return_value=sock) as create_socket, patch("time.monotonic", side_effect=lambda: now[0]), \
                patch("time.sleep", side_effect=sleep), patch.object(io.os.path, "exists", return_value=exists):
            yield sock, create_socket, now, waits

    def test_missing_socket_is_retried_and_each_attempt_is_closed(self):
        with self.socket_clock(exists=False) as (sock, create, _now, waits):
            sock.connect.side_effect = [FileNotFoundError(), None]
            self.assertTrue(io.wait_for_socket("socket", timeout=1))
            self.assertEqual(create.call_count, 2)
            self.assertEqual(sock.close.call_count, 2)
            self.assertEqual(waits, [0.1, 0.1])

    def test_permission_failure_stops_immediately(self):
        with self.socket_clock() as (sock, create, _now, waits):
            sock.connect.side_effect = PermissionError()
            self.assertFalse(io.wait_for_socket("socket", timeout=1))
            create.assert_called_once()
            sock.close.assert_called_once_with()
            self.assertEqual(waits, [0])

    def test_refused_socket_has_a_shorter_deadline(self):
        with self.socket_clock() as (sock, create, now, waits):
            sock.connect.side_effect = ConnectionRefusedError()
            self.assertFalse(io.wait_for_socket("socket", timeout=5, refused_timeout=0.2))
            self.assertLess(now[0] - 10, 0.3)
            self.assertTrue(all(delay > 0 for delay in waits[1:]))
            self.assertEqual(sock.close.call_count, create.call_count)

    def test_other_failures_expire_at_the_overall_deadline(self):
        with self.socket_clock() as (sock, create, now, _waits):
            sock.connect.side_effect = OSError("not available")
            self.assertFalse(io.wait_for_socket("socket", timeout=0.25))
            self.assertGreaterEqual(now[0] - 10, 0.25)
            self.assertEqual(sock.close.call_count, create.call_count)
        with self.socket_clock() as (_sock, create, _now, _waits):
            self.assertFalse(io.wait_for_socket("socket", timeout=0))
            create.assert_not_called()

    def test_writable_checks_owner_group_and_readonly_filesystems(self):
        info = SimpleNamespace(st_uid=1000, st_gid=2000, st_mode=0)
        with patch("xpra.os_util.getuid", return_value=9999), patch.object(io.os, "access", return_value=False), \
                patch.object(io.os, "stat", return_value=info), \
                patch.object(io.os, "statvfs", return_value=SimpleNamespace(f_flag=0)) as statvfs:
            for mode, uid, gid, expected in ((stat.S_IWUSR, 1000, 0, True), (stat.S_IWGRP, 0, 2000, True),
                                             (stat.S_IWUSR, 0, 2000, False), (0, 1000, 2000, False)):
                with self.subTest(mode=mode, uid=uid, gid=gid):
                    info.st_mode = mode
                    self.assertEqual(io.is_writable("file", uid, gid), expected)
            info.st_mode = stat.S_IWUSR
            statvfs.return_value.f_flag = os.ST_RDONLY
            self.assertFalse(io.is_writable("file", 1000, 2000))
            statvfs.side_effect = OSError("unavailable")
            self.assertTrue(io.is_writable("file", 1000, 2000))
        with patch.object(io.os, "access", return_value=False), patch.object(io.os, "stat", side_effect=OSError("missing")):
            self.assertFalse(io.is_writable("missing", 1000, 2000))

    def test_ldconfig_matching_and_architecture(self):
        data = "\tlibtest.so.1 (libc6,x86-64) => /lib64/libtest.so.1\n\tlibtest.so.1 (libc6) => /lib/libtest.so.1\n"
        proc = Mock()
        proc.communicate.return_value = data, ""
        with patch("subprocess.Popen", return_value=proc), patch.object(io.os.path, "exists", return_value=False):
            for arch, expected in (("x86_64", "/lib64/libtest.so.1"), ("aarch64", "/lib/libtest.so.1")):
                with self.subTest(arch=arch), patch.object(io.os, "uname", return_value=("", "", "", "", arch)):
                    proc.communicate.return_value = (data if arch == "x86_64" else data.splitlines()[1] + "\n"), ""
                    self.assertEqual(io.find_lib_ldconfig("test"), expected)
                    self.assertEqual(io.find_lib_ldconfig("missing"), "")

    def test_stderr_falls_back_to_syslog(self):
        logger = Mock()
        syslog = SimpleNamespace(syslog=logger, LOG_INFO=6, LOG_WARNING=4, LOG_ERR=3)
        with patch.object(sys, "stderr", None), patch.dict(sys.modules, {"syslog": syslog}):
            self.assertFalse(io.stderr_print("test"))
            io.info("info")
            io.warn("warning")
            io.error("error")
        self.assertEqual([call.args for call in logger.call_args_list], [(6, "info"), (4, "warning"), (3, "error")])


class TestAdditionalIOHelpers(unittest.TestCase):

    def test_libexec_discovery_and_absolute_command(self):
        absolute = os.path.abspath("test-tool")
        self.assertEqual(io.find_libexec_command(absolute), absolute)
        self.assertEqual(io.find_libexec_command(""), "")
        with patch("xpra.platform.paths.get_resources_dir", return_value="/resources"), \
                patch("xpra.platform.paths.get_app_dir", return_value="/app"), \
                patch.object(io.os.path, "exists", side_effect=lambda path: path == "/resources/libexec/xpra/test"):
            self.assertEqual(io.find_libexec_command("test"), "/resources/libexec/xpra/test")
            self.assertEqual(io.find_libexec_command("missing"), "")

    def test_proc_cmdline_latin1_fallback(self):
        with patch("xpra.os_util.POSIX", True), patch.object(io.os.path, "exists", return_value=True), \
                patch.object(io, "load_binary_file", return_value=b"command\0\xff\0"):
            self.assertEqual(io.get_proc_cmdline(42), ("command", "\xff"))

    def test_livefds_uses_fallback_limit(self):
        def fstat(fd):
            if fd in (0, 2):
                return object()
            raise OSError("closed")

        with patch.object(io.os, "sysconf", side_effect=ValueError, create=True), patch.object(io.os, "fstat", side_effect=fstat):
            self.assertEqual(io.livefds(), {0, 2})

    def test_binary_mode_success_and_failure(self):
        setmode = Mock()
        with patch("xpra.os_util.WIN32", True), patch.dict(sys.modules, {"msvcrt": SimpleNamespace(setmode=setmode)}), \
                patch.object(io.os, "O_BINARY", 32768, create=True), patch.object(io, "get_util_logger") as logger:
            io.setbinarymode(0)
            setmode.assert_called_once_with(0, 32768)
            setmode.side_effect = OSError("unavailable")
            io.setbinarymode(0)
            logger.return_value.error.assert_called_once()

    def test_pipe_cleanup_can_be_disabled(self):
        stdout, stderr = Mock(), Mock()
        with patch.object(sys, "stdout", stdout), patch.object(sys, "stderr", stderr), \
                patch.dict(os.environ, {"XPRA_CLEAN_STD_PIPES": "0"}):
            io.clean_std_pipes()
            stdout.close.assert_not_called()
            stderr.close.assert_not_called()
            os.environ["XPRA_CLEAN_STD_PIPES"] = "1"
            io.clean_std_pipes()
            stdout.close.assert_called_once_with()
            stderr.close.assert_called_once_with()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
