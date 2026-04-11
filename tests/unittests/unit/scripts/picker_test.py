# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import MagicMock, patch

from xpra.scripts.picker import (
    CONNECT_TIMEOUT,
    single_display_match,
    pick_vnc_display,
    pick_display,
    do_pick_display,
    connect_or_fail,
    get_sockpath,
    find_session_by_name,
)
from xpra.net.constants import SocketState
from xpra.scripts.config import InitException, InitExit


def _error_cb(msg):
    raise InitException(msg)


def _noop_error_cb(msg):
    pass


def _make_opts(socket_dir="/tmp", socket_dirs=(), system_proxy_socket=""):
    opts = MagicMock()
    opts.socket_dir = socket_dir
    opts.socket_dirs = list(socket_dirs)
    opts.system_proxy_socket = system_proxy_socket
    return opts


class TestConnectTimeout(unittest.TestCase):
    def test_is_positive_int(self):
        self.assertIsInstance(CONNECT_TIMEOUT, int)
        self.assertGreater(CONNECT_TIMEOUT, 0)


class TestSingleDisplayMatch(unittest.TestCase):
    def _srv(self, state, display, path):
        return (state, display, path)

    def test_single_live_server(self):
        dir_servers = {"/tmp": [self._srv(SocketState.LIVE, ":10", "/tmp/xpra/:10")]}
        sockdir, name, path = single_display_match(dir_servers, _error_cb)
        self.assertEqual(name, ":10")
        self.assertEqual(path, "/tmp/xpra/:10")

    def test_no_servers_calls_error_cb(self):
        with self.assertRaises(InitException):
            single_display_match({}, _error_cb)

    def test_multiple_servers_same_display_picks_first(self):
        dir_servers = {
            "/tmp": [self._srv(SocketState.LIVE, ":10", "/tmp/a")],
            "/run": [self._srv(SocketState.LIVE, ":10", "/run/b")],
        }
        sockdir, name, path = single_display_match(dir_servers, _error_cb)
        self.assertEqual(name, ":10")

    def test_multiple_servers_different_displays_calls_error_cb(self):
        dir_servers = {
            "/tmp": [
                self._srv(SocketState.LIVE, ":10", "/tmp/a"),
                self._srv(SocketState.LIVE, ":11", "/tmp/b"),
            ]
        }
        with self.assertRaises(InitException):
            single_display_match(dir_servers, _error_cb)

    def test_proxy_ignored_when_real_exists(self):
        dir_servers = {
            "/tmp": [
                self._srv(SocketState.LIVE, ":proxy-1", "/tmp/proxy"),
                self._srv(SocketState.LIVE, ":10", "/tmp/real"),
            ]
        }
        sockdir, name, path = single_display_match(dir_servers, _error_cb)
        self.assertEqual(name, ":10")

    def test_unknown_state_used_when_no_live(self):
        dir_servers = {"/tmp": [self._srv(SocketState.UNKNOWN, ":10", "/tmp/xpra/:10")]}
        sockdir, name, path = single_display_match(dir_servers, _error_cb)
        self.assertEqual(name, ":10")

    def test_custom_nomatch_message(self):
        try:
            single_display_match({}, _error_cb, nomatch="custom error")
        except InitException as e:
            self.assertIn("custom error", str(e))


class TestPickVncDisplay(unittest.TestCase):
    def test_explicit_display_number(self):
        result = pick_vnc_display(_error_cb, "vnc:5")
        self.assertEqual(result["display"], ":5")
        self.assertEqual(result["port"], 5905)
        self.assertEqual(result["host"], "localhost")
        self.assertEqual(result["type"], "tcp")

    def test_display_zero(self):
        result = pick_vnc_display(_error_cb, "vnc:0")
        self.assertEqual(result["port"], 5900)

    def test_invalid_display_number(self):
        with self.assertRaises(ValueError):
            pick_vnc_display(_error_cb, "vnc:abc")

    def test_no_display_scans_ports(self):
        # error_cb is called when no open ports are found; use a no-op to allow return {}
        with patch("xpra.scripts.picker.os.path.exists", return_value=False):
            result = pick_vnc_display(_noop_error_cb, "vnc")
        self.assertEqual(result, {})

    def test_no_display_finds_open_port(self):
        mock_sock = MagicMock()
        with patch("xpra.scripts.picker.os.path.exists", return_value=True), \
             patch("xpra.scripts.picker.X11_SOCKET_DIR", "/tmp"), \
             patch("xpra.net.socket_util.socket_connect", return_value=mock_sock):
            # patch the lazy import inside pick_vnc_display
            import xpra.net.socket_util as su
            orig = su.socket_connect
            su.socket_connect = lambda *a, **kw: mock_sock
            try:
                result = pick_vnc_display(_error_cb, "vnc")
            finally:
                su.socket_connect = orig
        self.assertEqual(result.get("type"), "vnc")
        self.assertEqual(result.get("display"), ":0")


class TestDoPickDisplay(unittest.TestCase):
    def _mock_dotxpra(self, socket_details=None):
        dotxpra = MagicMock()
        dotxpra.socket_details.return_value = socket_details or {}
        return dotxpra

    def test_no_args_single_live_server(self):
        dir_servers = {"/tmp": [(SocketState.LIVE, ":10", "/tmp/xpra/:10")]}
        dotxpra = self._mock_dotxpra(dir_servers)
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra):
            result = do_pick_display(_error_cb, opts, [])
        self.assertEqual(result["display"], ":10")
        self.assertEqual(result["type"], "socket")

    def test_no_args_no_servers_raises(self):
        dotxpra = self._mock_dotxpra({})
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra):
            with self.assertRaises(InitException):
                do_pick_display(_error_cb, opts, [])

    def test_no_args_root_falls_back_to_proxy_socket(self):
        dotxpra = self._mock_dotxpra({})
        opts = _make_opts(system_proxy_socket="/run/xpra/proxy")
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.getuid", return_value=0):
            result = do_pick_display(_error_cb, opts, [])
        self.assertEqual(result["display"], ":PROXY")

    def test_too_many_args_calls_error_cb(self):
        dotxpra = self._mock_dotxpra({})
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra):
            with self.assertRaises((InitException, AssertionError)):
                do_pick_display(_error_cb, opts, [":1", ":2"])

    def test_single_arg_calls_parse_display_name(self):
        opts = _make_opts()
        fake_desc = {"type": "tcp", "host": "host", "port": 10000}
        dotxpra = self._mock_dotxpra({})
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.parse_display_name", return_value=fake_desc) as mock_pdn:
            result = do_pick_display(_error_cb, opts, ["tcp://host:10000"])
        mock_pdn.assert_called_once()
        self.assertEqual(result, fake_desc)


class TestPickDisplay(unittest.TestCase):
    def test_vnc_arg_dispatches_to_pick_vnc(self):
        vnc_desc = {"type": "tcp", "host": "localhost", "port": 5905}
        with patch("xpra.scripts.picker.pick_vnc_display", return_value=vnc_desc) as mock_vnc:
            result = pick_display(_error_cb, _make_opts(), ["vnc:5"])
        mock_vnc.assert_called_once_with(_error_cb, "vnc:5")
        self.assertEqual(result, vnc_desc)

    def test_vnc_empty_falls_through_to_do_pick(self):
        fake_desc = {"type": "socket", "display": ":10"}
        with patch("xpra.scripts.picker.pick_vnc_display", return_value={}), \
             patch("xpra.scripts.picker.do_pick_display", return_value=fake_desc) as mock_do:
            result = pick_display(_error_cb, _make_opts(), ["vnc"])
        mock_do.assert_called_once()
        self.assertEqual(result, fake_desc)

    def test_non_vnc_goes_to_do_pick(self):
        fake_desc = {"type": "socket", "display": ":10"}
        with patch("xpra.scripts.picker.do_pick_display", return_value=fake_desc) as mock_do:
            pick_display(_error_cb, _make_opts(), [":10"])
        mock_do.assert_called_once()


class TestConnectOrFail(unittest.TestCase):
    def test_success(self):
        conn = MagicMock()
        import xpra.net.connect as connect_mod
        orig = getattr(connect_mod, "connect_to", None)
        connect_mod.connect_to = lambda *a, **kw: conn
        try:
            result = connect_or_fail({}, MagicMock())
            self.assertIs(result, conn)
        finally:
            if orig is not None:
                connect_mod.connect_to = orig

    def test_connection_closed_raises_init_exit(self):
        from xpra.net.bytestreams import ConnectionClosedException
        with patch("xpra.net.bytestreams.ConnectionClosedException", ConnectionClosedException):
            import xpra.net.bytestreams as bytestreams_mod
            import xpra.net.connect as connect_mod

            orig_connect_to = getattr(connect_mod, "connect_to", None)

            def fail_connect(display_desc, opts):
                raise bytestreams_mod.ConnectionClosedException("gone")

            connect_mod.connect_to = fail_connect
            try:
                with self.assertRaises(InitExit) as ctx:
                    connect_or_fail({}, MagicMock())
                self.assertIn("gone", str(ctx.exception))
            finally:
                if orig_connect_to is not None:
                    connect_mod.connect_to = orig_connect_to

    def test_init_exception_re_raised(self):
        import xpra.net.connect as connect_mod
        orig = getattr(connect_mod, "connect_to", None)
        connect_mod.connect_to = lambda *a, **kw: (_ for _ in ()).throw(InitException("init error"))
        try:
            with self.assertRaises(InitException):
                connect_or_fail({}, MagicMock())
        finally:
            if orig is not None:
                connect_mod.connect_to = orig

    def test_generic_exception_raises_init_exit(self):
        import xpra.net.connect as connect_mod
        orig = getattr(connect_mod, "connect_to", None)
        connect_mod.connect_to = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("oops"))
        try:
            with self.assertRaises(InitExit):
                connect_or_fail({}, MagicMock())
        finally:
            if orig is not None:
                connect_mod.connect_to = orig


class TestGetSockpath(unittest.TestCase):
    def _mock_dotxpra(self, socket_details=None, display_state=SocketState.LIVE):
        dotxpra = MagicMock()
        dotxpra.socket_details.return_value = socket_details if socket_details is not None else {}
        dotxpra.get_display_state.return_value = display_state
        return dotxpra

    def test_explicit_socket_path(self):
        result = get_sockpath({"socket_path": "/tmp/mysock", "display": ":10"}, _error_cb)
        self.assertEqual(result, "/tmp/mysock")

    def test_finds_socket_via_dotxpra(self):
        dir_servers = {"/tmp": [(SocketState.LIVE, ":10", "/tmp/xpra/:10")]}
        dotxpra = self._mock_dotxpra(dir_servers)
        desc = {"display": ":10", "socket_dir": "/tmp", "socket_dirs": []}
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.get_username_for_uid", return_value="user"):
            result = get_sockpath(desc, _error_cb, timeout=0)
        self.assertEqual(result, "/tmp/xpra/:10")

    def test_dead_socket_no_timeout_raises(self):
        dotxpra = self._mock_dotxpra({}, SocketState.DEAD)
        desc = {"display": ":10", "socket_dir": "/tmp", "socket_dirs": []}
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.get_username_for_uid", return_value="user"):
            with self.assertRaises(InitException):
                get_sockpath(desc, _error_cb, timeout=0)

    def test_dead_socket_with_timeout_waits(self):
        # After "waiting", the socket becomes LIVE
        dir_servers_live = {"/tmp": [(SocketState.LIVE, ":10", "/tmp/xpra/:10")]}
        dotxpra = MagicMock()
        # First call: no sockets; subsequent calls: live
        dotxpra.socket_details.side_effect = [{}, dir_servers_live]
        dotxpra.get_display_state.return_value = SocketState.DEAD
        desc = {"display": ":10", "socket_dir": "/tmp", "socket_dirs": []}
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.get_username_for_uid", return_value="user"), \
             patch("xpra.scripts.picker.monotonic", side_effect=[0.0, 0.0, 100.0]), \
             patch("xpra.scripts.picker.time.sleep"):
            result = get_sockpath(desc, _error_cb, timeout=1)
        self.assertEqual(result, "/tmp/xpra/:10")


class TestFindSessionByName(unittest.TestCase):
    def _make_proc(self, returncode, stdout):
        proc = MagicMock()
        proc.poll.return_value = returncode
        proc.communicate.return_value = (stdout.encode(), b"")
        return proc

    def test_no_sockets_returns_empty(self):
        dotxpra = MagicMock()
        dotxpra.socket_paths.return_value = []
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra):
            result = find_session_by_name(opts, "mysession")
        self.assertEqual(result, "")

    def test_matching_session_found(self):
        dotxpra = MagicMock()
        dotxpra.socket_paths.return_value = ["/tmp/xpra/:10"]
        proc = self._make_proc(0, "session-name=mysession\nuuid=abc123\n")
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.Popen", return_value=proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
             patch("xpra.scripts.picker.monotonic", side_effect=[0.0, 100.0]):
            result = find_session_by_name(opts, "mysession")
        self.assertEqual(result, "socket:///tmp/xpra/:10")

    def test_no_matching_session_returns_empty(self):
        dotxpra = MagicMock()
        dotxpra.socket_paths.return_value = ["/tmp/xpra/:10"]
        proc = self._make_proc(0, "session-name=other\nuuid=abc123\n")
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.Popen", return_value=proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
             patch("xpra.scripts.picker.monotonic", side_effect=[0.0, 100.0]):
            result = find_session_by_name(opts, "mysession")
        self.assertEqual(result, "")

    def test_multiple_matches_raises(self):
        dotxpra = MagicMock()
        dotxpra.socket_paths.return_value = ["/tmp/a", "/tmp/b"]
        # Each proc returns a different UUID so both entries end up in session_uuid_to_path
        uuids = iter(["uuid-001", "uuid-002"])

        def make_proc(_cmd, stdout, stderr):
            uid = next(uuids)
            return self._make_proc(0, f"session-name=mysession\nuuid={uid}\n")

        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.Popen", side_effect=make_proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
             patch("xpra.scripts.picker.monotonic", side_effect=[0.0, 100.0]):
            with self.assertRaises(InitException):
                find_session_by_name(opts, "mysession")

    def test_failed_proc_ignored(self):
        dotxpra = MagicMock()
        dotxpra.socket_paths.return_value = ["/tmp/xpra/:10"]
        proc = self._make_proc(1, "")  # non-zero returncode
        opts = _make_opts()
        with patch("xpra.scripts.picker._DotXpra", return_value=dotxpra), \
             patch("xpra.scripts.picker.Popen", return_value=proc), \
             patch("xpra.platform.paths.get_nodock_command", return_value=["xpra"]), \
             patch("xpra.scripts.picker.monotonic", side_effect=[0.0, 100.0]):
            result = find_session_by_name(opts, "mysession")
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
