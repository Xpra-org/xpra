#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import tempfile
import unittest

from xpra.util.env import OSEnvContext


class TestGetSessionDir(unittest.TestCase):

    def test_basic(self):
        from xpra.scripts.session import get_session_dir
        with tempfile.TemporaryDirectory() as base:
            result = get_session_dir("start", base, ":99", 0)
            assert isinstance(result, str)
            # display name ":99" → stripped to "99"
            assert "99" in result

    def test_empty_display(self):
        from xpra.scripts.session import get_session_dir
        with tempfile.TemporaryDirectory() as base:
            result = get_session_dir("start", base, "", 0)
            assert isinstance(result, str)

    def test_leading_colon_stripped(self):
        from xpra.scripts.session import get_session_dir
        with tempfile.TemporaryDirectory() as base:
            r1 = get_session_dir("start", base, "10", 0)
            r2 = get_session_dir("start", base, ":10", 0)
            assert r1 == r2

    def test_returns_string(self):
        from xpra.scripts.session import get_session_dir
        with tempfile.TemporaryDirectory() as base:
            for display in (":0", ":1", ":100", ""):
                result = get_session_dir("start", base, display, 0)
                assert isinstance(result, str)


class TestMakeSessionDir(unittest.TestCase):

    def test_creates_dir(self):
        from xpra.scripts.session import make_session_dir
        with tempfile.TemporaryDirectory() as base:
            session_dir = make_session_dir("start", base, ":77")
            assert os.path.isdir(session_dir), f"expected dir at {session_dir}"

    def test_idempotent(self):
        from xpra.scripts.session import make_session_dir
        with tempfile.TemporaryDirectory() as base:
            d1 = make_session_dir("start", base, ":55")
            d2 = make_session_dir("start", base, ":55")
            assert d1 == d2
            assert os.path.isdir(d1)


class TestSessionFilePath(unittest.TestCase):

    def test_with_env_set(self):
        from xpra.scripts.session import session_file_path
        with OSEnvContext(XPRA_SESSION_DIR="/tmp/xpra-test-session"):
            result = session_file_path("server.pid")
            assert result == "/tmp/xpra-test-session/server.pid"

    def test_empty_env_gives_join_with_empty(self):
        from xpra.scripts.session import session_file_path
        with OSEnvContext(XPRA_SESSION_DIR=""):
            result = session_file_path("foo")
            assert result == "foo"

    def test_nested_filename(self):
        from xpra.scripts.session import session_file_path
        with OSEnvContext(XPRA_SESSION_DIR="/tmp/sess"):
            assert session_file_path("sub/file") == "/tmp/sess/sub/file"


class TestSaveLoadSessionFile(unittest.TestCase):

    def test_save_no_session_dir(self):
        from xpra.scripts.session import save_session_file
        with OSEnvContext():
            os.environ.pop("XPRA_SESSION_DIR", None)
            result = save_session_file("test.txt", b"hello")
            assert result == ""

    def test_save_and_load(self):
        from xpra.scripts.session import save_session_file, load_session_file
        with tempfile.TemporaryDirectory() as d:
            with OSEnvContext(XPRA_SESSION_DIR=d):
                path = save_session_file("test-content.txt", b"hello-world")
                assert path != ""
                assert os.path.exists(path)
                data = load_session_file("test-content.txt")
                assert data == b"hello-world", repr(data)

    def test_save_str_content(self):
        from xpra.scripts.session import save_session_file, load_session_file
        with tempfile.TemporaryDirectory() as d:
            with OSEnvContext(XPRA_SESSION_DIR=d):
                save_session_file("strfile.txt", "hello string")
                data = load_session_file("strfile.txt")
                assert data == b"hello string", repr(data)

    def test_load_nonexistent(self):
        from xpra.scripts.session import load_session_file
        with OSEnvContext(XPRA_SESSION_DIR="/tmp/nonexistent-xpra-test-dir"):
            data = load_session_file("nope.txt")
            assert data == b"" or data is None or data == b""


class TestPidExists(unittest.TestCase):

    def test_zero_pid(self):
        from xpra.scripts.session import pidexists
        assert not pidexists(0)

    def test_negative_pid(self):
        from xpra.scripts.session import pidexists
        assert not pidexists(-1)

    def test_own_pid(self):
        from xpra.scripts.session import pidexists
        from xpra.os_util import POSIX
        if not POSIX:
            return
        # current process should exist
        assert pidexists(os.getpid())

    def test_large_nonexistent_pid(self):
        from xpra.scripts.session import pidexists
        # a very large pid is almost certainly not running
        # (Linux max is 4194304; but we can't assert False since it might exist)
        result = pidexists(4194305)
        assert result is False


class TestCleanSessionPath(unittest.TestCase):

    def test_nonexistent_path_is_noop(self):
        from xpra.scripts.session import clean_session_path
        # should not raise
        clean_session_path("/tmp/xpra-test-nonexistent-path-xpra")

    def test_removes_file(self):
        from xpra.scripts.session import clean_session_path
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            path = tf.name
        assert os.path.exists(path)
        clean_session_path(path)
        assert not os.path.exists(path)

    def test_removes_empty_dir(self):
        from xpra.scripts.session import clean_session_path
        d = tempfile.mkdtemp()
        assert os.path.isdir(d)
        clean_session_path(d)
        assert not os.path.exists(d)


class TestCleanSessionFiles(unittest.TestCase):

    def test_no_session_dir(self):
        from xpra.scripts.session import clean_session_files
        with OSEnvContext():
            os.environ.pop("XPRA_SESSION_DIR", None)
            # should not raise
            clean_session_files("server.pid")

    def test_cleans_known_file(self):
        from xpra.scripts.session import clean_session_files
        with tempfile.TemporaryDirectory() as d:
            fname = "server.pid"
            path = os.path.join(d, fname)
            with open(path, "w") as f:
                f.write("12345\n")
            with OSEnvContext(XPRA_SESSION_DIR=d):
                clean_session_files(fname)
            assert not os.path.exists(path)

    def test_glob_pattern(self):
        from xpra.scripts.session import clean_session_files
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                p = os.path.join(d, f"tmp-{i}.pid")
                with open(p, "w") as f:
                    f.write(str(os.getpid()))
            with OSEnvContext(XPRA_SESSION_DIR=d):
                clean_session_files("tmp-*.pid")
            remaining = [x for x in os.listdir(d) if x.startswith("tmp-")]
            assert remaining == [], f"expected all tmp-*.pid removed, got {remaining}"


class TestCleanSessionDir(unittest.TestCase):

    def test_empty_dir_removed(self):
        from xpra.scripts.session import clean_session_dir
        d = tempfile.mkdtemp()
        result = clean_session_dir(d)
        assert result is True
        assert not os.path.exists(d)

    def test_known_files_removed(self):
        from xpra.scripts.session import clean_session_dir
        d = tempfile.mkdtemp()
        for fname in ("cmdline", "config", "server.log"):
            with open(os.path.join(d, fname), "w") as f:
                f.write("test\n")
        result = clean_session_dir(d)
        assert result is True
        assert not os.path.exists(d)

    def test_unknown_files_prevent_removal(self):
        from xpra.scripts.session import clean_session_dir
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "unknown-file.xyz"), "w") as f:
            f.write("test\n")
        result = clean_session_dir(d)
        assert result is False
        assert os.path.isdir(d)
        # clean up
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
