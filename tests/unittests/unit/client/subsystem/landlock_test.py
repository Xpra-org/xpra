#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import tempfile
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base import features
from xpra.client.base.client import XpraClientBase
from xpra.client.base.factory import get_client_subsystems
from xpra.client.subsystem.landlock import LandLock
from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitExit, make_defaults_struct


class LandLockTest(unittest.TestCase):

    @staticmethod
    def mock_security():
        security = ModuleType("xpra.platform.posix.security")
        security.enforce_landlock = Mock(return_value=9)
        security.get_connection_landlock_auth_paths = Mock(return_value=((), ()))
        security.prepare_landlock_temp_dir = Mock(return_value=("/private", os.getpid()))
        security.cleanup_landlock_temp_dir = Mock()
        return security

    @staticmethod
    def make_landlock(mode="default"):
        opts = make_defaults_struct()
        opts.landlock = mode
        opts.download_path = "/downloads"
        client = XpraClientBase.__new__(XpraClientBase)
        client.subsystems = {}
        client.display_desc = {}
        landlock = LandLock(client)
        client.subsystems[LandLock.PREFIX] = landlock
        landlock.init(opts)
        return client, landlock, opts

    def test_factory_feature(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(features, "landlock", enabled):
                self.assertEqual(LandLock in get_client_subsystems(), enabled)

    def test_default_policy(self):
        _client, landlock, opts = self.make_landlock()
        security = self.mock_security()
        with patch.dict(os.environ), patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch.dict(sys.modules, {security.__name__: security}):
            landlock.run()
            self.assertTrue(landlock.enforced)
            self.assertEqual(os.environ["XPRA_DOWNLOAD_DIR"], opts.download_path)
        security.enforce_landlock.assert_called_once_with("default", ("/downloads",), read_paths=[],
                                                          required_paths=[], socket_paths=[], socket_dirs=[],
                                                          temp_dir="",
                                                          allow_socket_creation=True)

    def test_listener_order_and_single_installation(self):
        from xpra.client.subsystem.socket import NetworkListener
        client, landlock, opts = self.make_landlock("strict")
        events = []
        listener = NetworkListener(client)
        client.subsystems[listener.PREFIX] = listener
        listener.init(opts)
        sockets = [SimpleNamespace(socktype="socket", address="/controls/client")]
        security = self.mock_security()
        security.enforce_landlock.side_effect = lambda *a, **kw: events.append("landlock") or 9
        with patch.dict(os.environ), patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch.dict(sys.modules, {security.__name__: security}), \
             patch("xpra.client.subsystem.socket.create_sockets", return_value=[]), \
             patch("xpra.client.subsystem.socket.setup_local_sockets", side_effect=lambda *a, **kw: events.append("sockets") or sockets), \
             patch("xpra.client.subsystem.socket.start_thread", side_effect=lambda fn, *a, **kw: fn()), \
             patch("xpra.client.subsystem.socket.sleep"), \
             patch.object(NetworkListener, "start_listen_sockets", side_effect=lambda: events.append("listen")):
            client.load()
            self.assertFalse(landlock.enforced)
            client.run()
            client.setup_connection(None)
        self.assertEqual(events, ["sockets", "landlock", "listen"])
        security.enforce_landlock.assert_called_once()
        self.assertEqual(security.enforce_landlock.call_args.kwargs["socket_dirs"], ["/controls"])
        self.assertEqual(landlock.get_info()["landlock"]["abi"], 9)

    def test_listen_mode_uses_listener_lifecycle(self):
        from xpra.client.subsystem.socket import NetworkListener
        from xpra.scripts.main import enable_listen_mode, get_client_app
        client, _landlock, opts = self.make_landlock("strict")
        opts.bind = ["auto", "/reverse/client"]
        opts.socket_dirs = ["/reverse"]
        listener = NetworkListener(client)
        listener.listen_mode = True
        client.subsystems[listener.PREFIX] = listener
        listener.init(opts)
        self.assertEqual(listener.local_bind, ["/reverse/client"])
        self.assertEqual(listener.client_socket_dirs, opts.socket_dirs)
        sockets = [
            SimpleNamespace(socktype="socket", address="/reverse/client"),
            SimpleNamespace(socktype="socket", address="@abstract"),
            SimpleNamespace(socktype="tcp", address=("127.0.0.1", 12345)),
        ]
        security = self.mock_security()
        with patch("xpra.client.subsystem.socket.create_sockets", return_value=sockets), \
             patch("xpra.client.subsystem.socket.setup_local_sockets", return_value=[]), \
             patch("xpra.client.subsystem.socket.start_thread"), \
             patch("xpra.client.subsystem.landlock.LINUX", True), patch.dict(os.environ), \
             patch.dict(sys.modules, {security.__name__: security}):
            client.load()
            enable_listen_mode(client, opts)
            client.run()
        self.assertEqual(security.enforce_landlock.call_args.kwargs["socket_dirs"], ["/reverse"])
        self.assertIsNot(listener.connection_handler, listener._new_connection)
        self.assertTrue(listener.get_info()["listener"]["listen-mode"])
        with patch("xpra.scripts.main.create_client_app", return_value=(client, [], [])), \
             patch("xpra.scripts.main.connect_client_app") as connect:
            self.assertIs(get_client_app([], opts, [], "listen"), client)
        connect.assert_not_called()

    def test_listen_mode_accepts_a_server_with_no_initial_data(self):
        from xpra.client.subsystem.socket import NetworkListener
        from xpra.scripts.main import enable_listen_mode
        client, _landlock, opts = self.make_landlock("strict")
        client.idle_add = lambda fn, *args: fn(*args)
        listener = NetworkListener(client)
        client.subsystems[listener.PREFIX] = listener
        conn = object()
        protocol = Mock()
        with patch("xpra.net.socket_util.accept_connection", return_value=conn), \
             patch("xpra.net.socket_util.peek_connection", return_value=b""), \
             patch("xpra.util.thread.start_thread", side_effect=lambda fn, *a, **kw: fn(*kw["args"])), \
             patch.object(XpraClientBase, "make_protocol", return_value=protocol) as make_protocol, \
             patch.object(NetworkListener, "cleanup_sockets") as cleanup:
            enable_listen_mode(client, opts)
            self.assertTrue(listener.connection_handler(None))
        make_protocol.assert_called_once_with(conn)
        protocol.start.assert_called_once_with()
        cleanup.assert_called_once_with()

    def test_options_are_parsed_during_init(self):
        client, landlock, opts = self.make_landlock("strict")
        opts.ssl_cert = "/credentials/cert"
        opts.mmap = "/shared/new-mmap"
        landlock.init(opts)
        opts.ssl_cert = "/changed/cert"
        opts.download_path = "/changed/downloads"
        opts.mmap = "/changed/mmap"
        security = self.mock_security()
        with patch.dict(os.environ), patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch.dict(sys.modules, {security.__name__: security}):
            client.run()
        args, kwargs = security.enforce_landlock.call_args
        self.assertEqual(args, ("strict", ("/downloads", "/shared")))
        self.assertEqual(kwargs["required_paths"], ["/credentials/cert"])
        security.prepare_landlock_temp_dir.assert_called_once_with("/downloads")

    def test_disabled_or_non_linux(self):
        for linux, mode in ((True, "no"), (False, "default"), (False, "strict")):
            _client, landlock, _opts = self.make_landlock(mode)
            security = self.mock_security()
            with patch("xpra.client.subsystem.landlock.LINUX", linux), \
                 patch.dict(sys.modules, {security.__name__: security}):
                landlock.run()
            security.enforce_landlock.assert_not_called()
            self.assertFalse(landlock.enforced)

    def test_failure_aborts_client_run(self):
        for mode in ("default", "strict"):
            client, landlock, _opts = self.make_landlock(mode)
            security = self.mock_security()
            security.enforce_landlock.side_effect = OSError("unavailable")
            with patch("xpra.client.subsystem.landlock.LINUX", True), \
                 patch.dict(sys.modules, {security.__name__: security}), \
                 self.assertRaisesRegex(InitExit, "failed to restrict the client") as raised:
                client.run()
            self.assertEqual(raised.exception.status, ExitCode.FAILURE)
            self.assertFalse(landlock.enforced)
            if mode == "strict":
                security.cleanup_landlock_temp_dir.assert_called_once_with("/private", os.getpid())
                self.assertEqual(landlock.temp_dir, "")
            else:
                security.cleanup_landlock_temp_dir.assert_not_called()

    def test_initialization_failure_aborts_startup(self):
        client, _landlock, opts = self.make_landlock()
        peer_init = Mock()
        client.subsystems["peer"] = SimpleNamespace(init=peer_init)
        with patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch("xpra.platform.posix.security.get_landlock_auth_paths", side_effect=ImportError("missing dependency")), \
             self.assertRaisesRegex(InitExit, "failed to initialize client Landlock"):
            client._dispatch_fire("init", opts)
        peer_init.assert_not_called()

    def test_temp_cleanup_after_subsystems_and_connection(self):
        from xpra.platform.posix import security
        client, landlock, _opts = self.make_landlock("strict")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir), \
             patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch("xpra.client.base.client.reaper_cleanup"), patch("xpra.client.base.client.stop_asyncio_loop"):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            landlock.temp_dir, landlock.temp_dir_owner = security.prepare_landlock_temp_dir(directory)
            path = landlock.temp_dir
            events = []

            def release(name):
                events.append((name, os.path.isdir(path)))

            client.subsystems["files"] = SimpleNamespace(cleanup=lambda: release("files"), late_cleanup=lambda: None)
            client._protocol = SimpleNamespace(close=lambda: release("protocol"))
            client.verify_connected_timer = 0
            client.cleanup()
            self.assertEqual(events, [("files", True), ("protocol", True)])
            self.assertFalse(os.path.exists(path))
            client.cleanup()

    def test_cleanup_only_removes_its_own_directory(self):
        from xpra.platform.posix import security
        _client, first, _opts = self.make_landlock("strict")
        _client, second, _opts = self.make_landlock("strict")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir):
            for index, landlock in enumerate((first, second)):
                os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
                os.environ.pop("XPRA_LANDLOCK_TMP_OWNER", None)
                landlock.temp_dir, landlock.temp_dir_owner = security.prepare_landlock_temp_dir(
                    os.path.join(directory, str(index)),
                )
            first_path, second_path = first.temp_dir, second.temp_dir
            first.late_cleanup()
            self.assertFalse(os.path.exists(first_path))
            self.assertTrue(os.path.isdir(second_path))
            self.assertEqual(os.environ["XPRA_LANDLOCK_TMP_DIR"], second_path)
            second.late_cleanup()
            self.assertFalse(os.path.exists(second_path))

    def test_strict_target_resources(self):
        client, landlock, _opts = self.make_landlock("strict")
        desc = {"type": "socket", "socket_path": "/server/socket"}
        security = self.mock_security()
        security.get_connection_landlock_auth_paths.return_value = (("/known-hosts",), ("/cert",))
        with patch.dict(os.environ), patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch.dict(sys.modules, {security.__name__: security}), \
             patch("xpra.scripts.picker.get_sockpath", return_value="/server/socket"):
            client.display_desc = desc
            client.setup_connection(None)
        security.enforce_landlock.assert_called_once_with("strict", ("/downloads",),
                                                          read_paths=["/known-hosts", "/cert"], required_paths=["/cert"],
                                                          socket_paths=["/server/socket"], socket_dirs=[],
                                                          temp_dir="/private",
                                                          allow_socket_creation=False)

    def test_missing_target_does_not_create_temp_storage(self):
        client, landlock, _opts = self.make_landlock("strict")
        security = self.mock_security()
        error = InitExit(ExitCode.SERVER_NOT_FOUND, "server socket not found")
        with patch("xpra.client.subsystem.landlock.LINUX", True), \
             patch.dict(sys.modules, {security.__name__: security}), \
             patch("xpra.scripts.picker.get_sockpath", side_effect=error), self.assertRaises(InitExit) as raised:
            client.display_desc = {"type": "socket"}
            client.run()
        self.assertIs(raised.exception, error)
        security.prepare_landlock_temp_dir.assert_not_called()
        security.enforce_landlock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
