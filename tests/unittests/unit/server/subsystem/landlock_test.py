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

from xpra.exit_codes import ExitCode
from xpra.scripts.config import InitException, InitExit, make_defaults_struct
from xpra.server import features
from xpra.server.core import ServerCore, get_instance_subsystem_classes
from xpra.server.subsystem.landlock import LandLock


class LandLockTest(unittest.TestCase):

    @staticmethod
    def make_landlock(mode="strict"):
        opts = make_defaults_struct()
        opts.landlock = mode
        server = ServerCore.__new__(ServerCore)
        server.subsystems = {}
        server.sockets = []
        landlock = LandLock(server)
        server.subsystems[LandLock.PREFIX] = landlock
        landlock.init(opts)
        server.start_listen_sockets = Mock()
        server.init_packet_handlers = Mock()
        server.add_core_control_commands = Mock()
        return server, landlock, opts

    @staticmethod
    def mock_modules(events):
        security = ModuleType("xpra.platform.posix.security")
        security.enforce_landlock = Mock(side_effect=lambda *a, **kw: events.append("landlock") or 9)
        security.prepare_landlock_temp_dir = Mock(return_value=("/private", os.getpid()))
        security.cleanup_landlock_temp_dir = Mock()
        menu_helper = ModuleType("xpra.platform.posix.menu_helper")
        menu_helper.prepare_menu_icon_cache_dir = lambda: events.append("cache") or "/cache"
        return {security.__name__: security, menu_helper.__name__: menu_helper}

    def test_factory_feature_and_order(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), patch.object(features, "landlock", enabled):
                classes = get_instance_subsystem_classes()
                self.assertEqual(LandLock in classes, enabled)
                if enabled:
                    self.assertIs(classes[0], LandLock)

    def test_feature_uses_current_option(self):
        saved = {name: value for name, value in vars(features).items() if isinstance(value, bool)}
        for linux, mode, expected in ((True, "no", False), (True, "default", True), (True, "strict", True),
                                      (False, "strict", False)):
            opts = make_defaults_struct()
            opts.landlock = mode
            with self.subTest(linux=linux, mode=mode), patch.dict(vars(features), saved), \
                 patch.object(features, "LINUX", linux), patch.dict(os.environ, {"XPRA_ENFORCE_FEATURES": "0"}), \
                 patch("importlib.util.find_spec", return_value=object()):
                features.set_server_features(opts, "encoder")
                self.assertEqual(features.landlock, expected)
                self.assertEqual(LandLock in get_instance_subsystem_classes(), expected)

    def test_setup_order_and_single_installation(self):
        server, landlock, opts = self.make_landlock()
        events = []
        modules = self.mock_modules(events)
        server.subsystems["dbus"] = SimpleNamespace(
            enabled=True, env={}, init_dbus_env=lambda: events.append("dbus"), setup=lambda: events.append("dbus-setup"),
        )
        server.subsystems["peer"] = SimpleNamespace(setup=lambda: events.append("peer"))
        server.sockets = [
            SimpleNamespace(socktype="socket", address="/sockets/xpra", options={}),
            SimpleNamespace(socktype="socket", address="@abstract", options={}),
            SimpleNamespace(socktype="tcp", address=("127.0.0.1", 12345), options={}),
        ]
        server.start_listen_sockets.side_effect = lambda: events.append("listen")
        with patch("xpra.server.subsystem.landlock.LINUX", True), patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {"XPRA_SESSION_DIR": "/sessions/100"}):
            server.setup()
            landlock.setup()
        self.assertEqual(events, ["dbus", "cache", "landlock", "dbus-setup", "peer", "listen"])
        self.assertTrue(landlock.enforced)
        self.assertEqual(landlock.get_info(None)["landlock"]["abi"], 9)
        modules["xpra.platform.posix.security"].enforce_landlock.assert_called_once_with(
            "strict", ("/sessions/100", "/cache"), read_paths=(), required_paths=(),
            socket_dirs=["/sockets"], cleanup_dirs=("/sessions",), temp_dir="/private", allow_socket_creation=False,
        )

    def test_options_are_parsed_during_init(self):
        server, landlock, opts = self.make_landlock()
        opts.ssl_cert = "/credentials/cert"
        opts.mmap = "/shared/new-mmap"
        landlock.init(opts)
        opts.ssl_cert = "/changed/cert"
        opts.mmap = "/changed/mmap"
        modules = self.mock_modules([])
        with patch("xpra.server.subsystem.landlock.LINUX", True), patch.dict(sys.modules, modules), \
             patch.dict(os.environ, {"XPRA_SESSION_DIR": "/sessions/100"}):
            server.setup()
        args, kwargs = modules["xpra.platform.posix.security"].enforce_landlock.call_args
        self.assertEqual(args, ("strict", ("/sessions/100", "/cache", "/shared")))
        self.assertEqual(kwargs["required_paths"], ("/credentials/cert",))

    def test_auth_files(self):
        server, landlock, _opts = self.make_landlock()
        server.subsystems["auth"] = SimpleNamespace(auth_classes={
            "tcp": (("file", None, None, {"filename": "password", "exec_cwd": "/credentials"}),),
        })
        server.sockets = [SimpleNamespace(options={"ssh-host-key": "/keys/host", "ssl-key": "/keys/tls"})]
        self.assertEqual(landlock.get_auth_paths(), ("/keys/host", "/keys/tls", "/credentials/password"))

    def test_wayland_backend_starts_after_confinement(self):
        from xpra.wayland.server.subsystem.manager import WaylandManager
        server, _landlock, _opts = self.make_landlock()
        events = []
        modules = self.mock_modules(events)
        wayland = WaylandManager(server)
        # setup_display already bound the socket before app.setup is called.
        wayland.socket_name = "wayland-0"
        wayland.compositor = SimpleNamespace(start_backend=lambda: events.append("backend"))
        server.subsystems["wayland"] = wayland
        server.subsystems["display"] = SimpleNamespace(setup=lambda: events.append("display"))
        with patch("xpra.server.subsystem.landlock.LINUX", True), patch.dict(sys.modules, modules):
            server.setup()
        self.assertEqual(events, ["cache", "landlock", "backend", "display"])
        self.assertTrue(wayland.started)

    def test_disabled_or_non_linux(self):
        for linux, mode in ((True, "no"), (False, "default"), (False, "strict")):
            server, landlock, _opts = self.make_landlock(mode)
            modules = self.mock_modules([])
            with patch("xpra.server.subsystem.landlock.LINUX", linux), patch.dict(sys.modules, modules):
                server.setup()
                landlock.cleanup()
            security = modules["xpra.platform.posix.security"]
            security.enforce_landlock.assert_not_called()
            security.prepare_landlock_temp_dir.assert_not_called()
            security.cleanup_landlock_temp_dir.assert_not_called()
            self.assertFalse(landlock.enforced)

    def test_failure_aborts_setup(self):
        for mode in ("default", "strict"):
            server, landlock, _opts = self.make_landlock(mode)
            peer_setup = Mock()
            server.subsystems["peer"] = SimpleNamespace(setup=peer_setup)
            modules = self.mock_modules([])
            security = modules["xpra.platform.posix.security"]
            security.enforce_landlock.side_effect = OSError("unavailable")
            with patch("xpra.server.subsystem.landlock.LINUX", True), patch.dict(sys.modules, modules), \
                 self.assertRaisesRegex(InitExit, "failed to restrict the server") as raised:
                server.setup()
            self.assertEqual(raised.exception.status, ExitCode.FAILURE)
            self.assertFalse(landlock.enforced)
            peer_setup.assert_not_called()
            server.start_listen_sockets.assert_not_called()
            if mode == "strict":
                security.cleanup_landlock_temp_dir.assert_called_once_with("/private", os.getpid())
                self.assertEqual(landlock.temp_dir, "")
            else:
                security.cleanup_landlock_temp_dir.assert_not_called()

    def test_initialization_failure_aborts_startup(self):
        server, _landlock, opts = self.make_landlock()
        peer_init = Mock()
        server.subsystems["peer"] = SimpleNamespace(init=peer_init)
        with patch("xpra.server.subsystem.landlock.LINUX", True), \
             patch("xpra.platform.posix.security.get_landlock_auth_paths", side_effect=ImportError("missing dependency")), \
             self.assertRaisesRegex(InitExit, "failed to initialize server Landlock"):
            server._dispatch_fire("init", opts)
        peer_init.assert_not_called()

    def test_temp_cleanup_before_session_removal(self):
        from xpra.platform.posix import security
        server, landlock, _opts = self.make_landlock()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir), \
             patch("xpra.server.subsystem.landlock.LINUX", True):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            session_dir = os.path.join(directory, "session")
            os.mkdir(session_dir)
            landlock.temp_dir, landlock.temp_dir_owner = security.prepare_landlock_temp_dir(session_dir)
            path = landlock.temp_dir
            events = []

            def release():
                self.assertTrue(os.path.isdir(path))
                events.append("peer")

            def remove_session(_stop):
                self.assertFalse(os.path.exists(path))
                os.rmdir(session_dir)
                events.append("session")

            server.subsystems["session-files"] = SimpleNamespace(cleanup=lambda: None, late_cleanup=remove_session)
            server.subsystems["peer"] = SimpleNamespace(cleanup=release, late_cleanup=lambda _stop: None)
            server._dispatch_fire("cleanup", reverse=True)
            server._dispatch_fire("late_cleanup", True, reverse=True)
            self.assertEqual(events, ["peer", "session"])
            self.assertFalse(os.path.exists(session_dir))

    def test_failed_enforcement_cleans_private_temp(self):
        from xpra.platform.posix import security
        server, landlock, _opts = self.make_landlock()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ), \
             patch.object(tempfile, "tempdir", tempfile.tempdir), \
             patch("xpra.server.subsystem.landlock.LINUX", True), \
             patch("xpra.platform.posix.menu_helper.prepare_menu_icon_cache_dir", return_value=directory):
            os.environ.pop("XPRA_LANDLOCK_TMP_DIR", None)
            os.environ["XPRA_SESSION_DIR"] = directory
            paths = []

            def fail(*_args, **_kwargs):
                paths.append(landlock.temp_dir)
                raise OSError("unavailable")

            with patch.object(security, "enforce_landlock", side_effect=fail), self.assertRaises(InitExit):
                server.setup()
            self.assertFalse(os.path.exists(paths[0]))
            self.assertNotIn("XPRA_LANDLOCK_TMP_DIR", os.environ)

    def test_auth_path_failure_aborts_setup_before_temp_creation(self):
        server, _landlock, _opts = self.make_landlock()
        server.sockets = [SimpleNamespace(socktype="tcp", address=("127.0.0.1", 12345), options={"auth": "invalid"})]
        modules = self.mock_modules([])
        security = modules["xpra.platform.posix.security"]
        with patch("xpra.server.subsystem.landlock.LINUX", True), patch.dict(sys.modules, modules), \
             patch("xpra.auth.auth_helper.get_auth_module", side_effect=InitException("missing auth module")), \
             self.assertRaisesRegex(InitExit, "missing auth module"):
            server.setup()
        security.prepare_landlock_temp_dir.assert_not_called()
        security.enforce_landlock.assert_not_called()
        server.start_listen_sockets.assert_not_called()


if __name__ == "__main__":
    unittest.main()
