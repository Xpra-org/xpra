#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import io
import os
import socket
import tempfile
import unittest
from subprocess import TimeoutExpired
from unittest.mock import patch, MagicMock

from xpra.net.constants import SocketState
from xpra.scripts.config import InitException, InitInfo
from xpra.scripts.sessions import (
    WAIT_SERVER_TIMEOUT,
    LIST_REPROBE_TIMEOUT,
    may_cleanup_socket,
    get_xpra_sessions,
    identify_new_socket,
    clean_sockets,
    run_list_sessions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture(fn, *args, **kwargs):
    """Call fn and return (return_value, stdout_text)."""
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        rv = fn(*args, **kwargs)
    return rv, buf.getvalue()


def _mock_dotxpra(socket_details=None, displays=None):
    d = MagicMock()
    d.socket_details.return_value = socket_details or {}
    d.displays.return_value = displays or []
    return d


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):

    def test_wait_server_timeout_positive(self):
        assert isinstance(WAIT_SERVER_TIMEOUT, int)
        assert WAIT_SERVER_TIMEOUT > 0

    def test_list_reprobe_timeout_positive(self):
        assert isinstance(LIST_REPROBE_TIMEOUT, int)
        assert LIST_REPROBE_TIMEOUT > 0


# ---------------------------------------------------------------------------
# may_cleanup_socket
# ---------------------------------------------------------------------------

class TestMayCleanupSocket(unittest.TestCase):

    def test_live_state_not_cleaned(self):
        _, out = _capture(may_cleanup_socket, SocketState.LIVE, ":1", "/tmp/nonexistent")
        assert "LIVE" in out
        assert ":1" in out
        assert "cleaned up" not in out

    def test_dead_state_shown_in_output(self):
        _, out = _capture(may_cleanup_socket, SocketState.DEAD, ":2", "/tmp/nonexistent")
        assert "DEAD" in out
        assert ":2" in out

    def test_plain_string_state(self):
        _, out = _capture(may_cleanup_socket, "custom", ":3", "/tmp/x")
        assert "custom" in out

    def test_nonexistent_path_reports_failure(self):
        _, out = _capture(
            may_cleanup_socket, SocketState.DEAD, ":5", "/tmp/xpra-test-no-such-socket",
        )
        assert "delete failed" in out

    def test_owned_file_is_deleted(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            assert os.path.exists(path)
            _, out = _capture(may_cleanup_socket, SocketState.DEAD, ":6", path)
            assert not os.path.exists(path), "file should have been deleted"
            assert "cleaned up" in out
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_custom_clean_states(self):
        # LIVE is not in the default clean_states, but we can pass it explicitly
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            _capture(may_cleanup_socket, SocketState.LIVE, ":7", path,
                     clean_states=(SocketState.LIVE,))
            assert not os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_output_ends_with_newline(self):
        _, out = _capture(may_cleanup_socket, SocketState.UNKNOWN, ":8", "/tmp/x")
        assert out.endswith("\n")


# ---------------------------------------------------------------------------
# get_xpra_sessions
# ---------------------------------------------------------------------------

class TestGetXpraSessions(unittest.TestCase):

    def test_empty_socket_details(self):
        result = get_xpra_sessions(_mock_dotxpra(), query=False)
        assert result == {}

    def test_ignored_state_excluded(self):
        dotxpra = _mock_dotxpra(socket_details={
            "/run/user/1000/xpra": [
                (SocketState.UNKNOWN, ":1", "/run/user/1000/xpra/:1"),
            ]
        })
        result = get_xpra_sessions(dotxpra, ignore_state=(SocketState.UNKNOWN,), query=False)
        assert ":1" not in result

    def test_non_ignored_state_included(self):
        dotxpra = _mock_dotxpra(socket_details={
            "/run/user/1000/xpra": [
                (SocketState.LIVE, ":2", "/run/user/1000/xpra/:2"),
            ]
        })
        result = get_xpra_sessions(dotxpra, ignore_state=(SocketState.UNKNOWN,), query=False)
        assert ":2" in result

    def test_session_contains_state_and_paths(self):
        sockdir = "/run/user/1000/xpra"
        sockpath = sockdir + "/:3"
        dotxpra = _mock_dotxpra(socket_details={
            sockdir: [(SocketState.LIVE, ":3", sockpath)]
        })
        result = get_xpra_sessions(dotxpra, ignore_state=(), query=False)
        session = result[":3"]
        assert session["state"] == SocketState.LIVE
        assert session["socket-dir"] == sockdir
        assert session["socket-path"] == sockpath

    def test_socket_stat_populates_uid_gid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                dotxpra = _mock_dotxpra(socket_details={
                    tmpdir: [(SocketState.LIVE, ":4", sockpath)]
                })
                result = get_xpra_sessions(dotxpra, ignore_state=(), query=False)
                session = result[":4"]
                assert "uid" in session
                assert "gid" in session
                assert session["uid"] == os.getuid()
            finally:
                srv.close()

    def test_inaccessible_socket_no_uid(self):
        dotxpra = _mock_dotxpra(socket_details={
            "/no/such/dir": [(SocketState.LIVE, ":5", "/no/such/dir/sock")]
        })
        result = get_xpra_sessions(dotxpra, ignore_state=(), query=False)
        session = result[":5"]
        assert "uid" not in session

    def test_query_false_no_subprocess(self):
        dotxpra = _mock_dotxpra(socket_details={
            "/tmp": [(SocketState.LIVE, ":6", "/tmp/nonexistent-sock")]
        })
        with patch("xpra.scripts.sessions.Popen") as mock_popen:
            get_xpra_sessions(dotxpra, ignore_state=(), query=False)
        mock_popen.assert_not_called()

    def test_query_true_merges_subprocess_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                dotxpra = _mock_dotxpra(socket_details={
                    tmpdir: [(SocketState.LIVE, ":7", sockpath)]
                })
                mock_proc = MagicMock()
                mock_proc.returncode = 0
                mock_proc.communicate.return_value = (b"session-name=mytest\n", b"")
                with patch("xpra.scripts.sessions.Popen", return_value=mock_proc), \
                     patch("xpra.platform.paths.get_xpra_command", return_value=["xpra"]):
                    result = get_xpra_sessions(dotxpra, ignore_state=(), query=True)
                assert result[":7"].get("session-name") == "mytest"
            finally:
                srv.close()

    def test_query_subprocess_timeout_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sockpath = os.path.join(tmpdir, "test.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(sockpath)
            srv.listen(1)
            try:
                dotxpra = _mock_dotxpra(socket_details={
                    tmpdir: [(SocketState.LIVE, ":8", sockpath)]
                })
                mock_proc = MagicMock()
                mock_proc.communicate.side_effect = TimeoutExpired(cmd="xpra", timeout=1)
                with patch("xpra.scripts.sessions.Popen", return_value=mock_proc), \
                     patch("xpra.platform.paths.get_xpra_command", return_value=["xpra"]):
                    result = get_xpra_sessions(dotxpra, ignore_state=(), query=True)
                # session still present, just without the extra fields
                assert ":8" in result
            finally:
                srv.close()

    def test_multiple_displays_multiple_socket_dirs(self):
        dotxpra = _mock_dotxpra(socket_details={
            "/run/xpra": [
                (SocketState.LIVE, ":10", "/run/xpra/:10"),
                (SocketState.DEAD, ":11", "/run/xpra/:11"),
            ],
            "/tmp/xpra": [
                (SocketState.LIVE, ":12", "/tmp/xpra/:12"),
            ],
        })
        result = get_xpra_sessions(dotxpra, ignore_state=(), query=False)
        assert set(result.keys()) == {":10", ":11", ":12"}


# ---------------------------------------------------------------------------
# exec_and_parse
# ---------------------------------------------------------------------------

class TestExecAndParse(unittest.TestCase):

    def _run(self, stdout="", stderr="", returncode=0, raises=None):
        proc = MagicMock()
        if raises:
            proc.communicate.side_effect = raises
        else:
            proc.communicate.return_value = (stdout, stderr)
        proc.returncode = returncode
        with patch("xpra.scripts.sessions.Popen", return_value=proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]):
            from xpra.scripts.sessions import exec_and_parse as _exec_and_parse
            return _exec_and_parse("id", ":0")

    def test_empty_output_returns_empty_dict(self):
        result = self._run(stdout="", stderr="")
        assert result == {}

    def test_key_value_lines_parsed(self):
        result = self._run(stdout="session-name=hello\nversion=6.0\n")
        assert result["session-name"] == "hello"
        assert result["version"] == "6.0"

    def test_value_with_equals_splits_on_first(self):
        result = self._run(stdout="key=a=b=c\n")
        assert result["key"] == "a=b=c"

    def test_lines_without_equals_skipped(self):
        result = self._run(stdout="no-equals-here\nkey=val\n")
        assert "no-equals-here" not in result
        assert result["key"] == "val"

    def test_falls_back_to_stderr_when_stdout_empty(self):
        result = self._run(stdout="", stderr="key=fromstderr\n")
        assert result["key"] == "fromstderr"

    def test_popen_exception_returns_empty_dict(self):
        result = self._run(raises=OSError("no such file"))
        assert result == {}


# ---------------------------------------------------------------------------
# identify_new_socket
# ---------------------------------------------------------------------------

class TestIdentifyNewSocket(unittest.TestCase):

    def test_dead_proc_raises_immediately(self):
        proc = MagicMock()
        proc.poll.return_value = 1          # process already exited with error
        dotxpra = _mock_dotxpra()
        dotxpra.socket_paths.return_value = set()

        with patch("xpra.scripts.sessions.WAIT_SERVER_TIMEOUT", 0), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]):
            with self.assertRaises(InitException):
                identify_new_socket(proc, dotxpra, set(), ":0", "uuid-1", ":0")

    def test_new_socket_with_matching_uuid_returned(self):
        proc = MagicMock()
        proc.poll.return_value = None       # still running

        dotxpra = _mock_dotxpra()
        dotxpra.socket_paths.return_value = {"/tmp/xpra/:99"}

        id_proc = MagicMock()
        id_proc.returncode = 0
        id_proc.communicate.return_value = ("uuid=test-uuid-42\ndisplay=:99\n", "")

        with patch("xpra.scripts.sessions.WAIT_SERVER_TIMEOUT", 5), \
             patch("xpra.scripts.sessions.Popen", return_value=id_proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]):
            path, display = identify_new_socket(
                proc, dotxpra, set(), ":99", "test-uuid-42", ":99",
            )
        assert path == "/tmp/xpra/:99"
        assert display == ":99"

    def test_socket_with_wrong_uuid_skipped(self):
        proc = MagicMock()
        proc.poll.return_value = None

        dotxpra = _mock_dotxpra()
        dotxpra.socket_paths.return_value = {"/tmp/xpra/:98"}

        id_proc = MagicMock()
        id_proc.returncode = 0
        id_proc.communicate.return_value = ("uuid=wrong-uuid\ndisplay=:98\n", "")

        with patch("xpra.scripts.sessions.WAIT_SERVER_TIMEOUT", 0), \
             patch("xpra.scripts.sessions.Popen", return_value=id_proc), \
             patch("xpra.scripts.sessions.time") as mock_time, \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]):
            # monotonic needs to advance past the timeout quickly
            mock_time.sleep = MagicMock()
            with patch("xpra.scripts.sessions.monotonic", side_effect=[0.0, 1.0, 2.0]):
                with self.assertRaises(InitException):
                    identify_new_socket(
                        proc, dotxpra, set(), ":98", "correct-uuid", ":98",
                    )

    def test_subprocess_nonzero_returncode_skipped(self):
        proc = MagicMock()
        proc.poll.return_value = None

        dotxpra = _mock_dotxpra()
        dotxpra.socket_paths.return_value = {"/tmp/xpra/:97"}

        id_proc = MagicMock()
        id_proc.returncode = 1             # failure
        id_proc.communicate.return_value = ("", "")

        with patch("xpra.scripts.sessions.WAIT_SERVER_TIMEOUT", 0), \
             patch("xpra.scripts.sessions.Popen", return_value=id_proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]):
            with patch("xpra.scripts.sessions.monotonic", side_effect=[0.0, 1.0]):
                with self.assertRaises(InitException):
                    identify_new_socket(
                        proc, dotxpra, set(), ":97", "some-uuid", ":97",
                    )


# ---------------------------------------------------------------------------
# clean_sockets
# ---------------------------------------------------------------------------

class TestCleanSockets(unittest.TestCase):

    def test_empty_list_does_nothing(self):
        dotxpra = _mock_dotxpra()
        _, out = _capture(clean_sockets, dotxpra, [])
        assert out == ""
        dotxpra.get_server_state.assert_not_called()

    def test_unowned_sockets_skipped(self):
        dotxpra = _mock_dotxpra()
        # pass a path that doesn't exist — os.stat raises OSError → skipped
        sockets = [("/run/xpra", ":1", "/no/such/path")]
        _, out = _capture(clean_sockets, dotxpra, sockets, timeout=0)
        assert out == ""
        dotxpra.get_server_state.assert_not_called()

    def test_owned_dead_socket_cleaned(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            dotxpra = _mock_dotxpra()
            dotxpra.get_server_state.return_value = SocketState.DEAD
            sockets = [("/tmp", ":2", path)]
            _, out = _capture(clean_sockets, dotxpra, sockets, timeout=1)
            assert "DEAD" in out
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# run_list_sessions
# ---------------------------------------------------------------------------

class TestRunListSessions(unittest.TestCase):

    def test_extra_args_raises_init_info(self):
        opts = MagicMock()
        with self.assertRaises(InitInfo):
            run_list_sessions(["unexpected-arg"], opts)

    def test_empty_sessions_prints_found_zero(self):
        opts = MagicMock()
        with patch("xpra.scripts.sessions.get_xpra_sessions", return_value={}), \
             patch("xpra.platform.dotxpra.DotXpra"):
            _, out = _capture(run_list_sessions, [], opts)
        assert "0" in out

    def test_session_row_printed(self):
        opts = MagicMock()
        sessions = {
            ":5": {
                "state": SocketState.LIVE,
                "session-type": "seamless",
                "username": "alice",
                "session-name": "mywork",
            }
        }
        with patch("xpra.scripts.sessions.get_xpra_sessions", return_value=sessions), \
             patch("xpra.platform.dotxpra.DotXpra"):
            _, out = _capture(run_list_sessions, [], opts)
        assert ":5" in out
        assert "alice" in out
        assert "mywork" in out


def main():
    unittest.main()


if __name__ == "__main__":
    main()
