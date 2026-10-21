#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.os_util import OSX, POSIX
from xpra.util.env import OSEnvContext


def noop(*_args, **_kwargs):
    pass


class FakeLogger:
    error = noop
    warn = noop
    info = noop
    debug = noop

    @staticmethod
    def is_debug_enabled() -> bool:
        return False

    def __call__(self, *args, **kwargs):
        noop(*args, **kwargs)


class DBUSTest(unittest.TestCase):

    @staticmethod
    def make_manager(mode, dbus="yes"):
        from xpra.server.subsystem.dbus import DbusManager
        manager = DbusManager(SimpleNamespace(subsystems={}))
        manager.init(SimpleNamespace(mode=mode, dbus=dbus, dbus_launch="dbus-launch", dbus_control=True))
        return manager

    def test_existing_session_bus(self):
        from xpra.server import features
        from xpra.server.subsystem.dbus import DbusManager

        for mode in ("shadow", "shadow-screen", "shadow-device", "expand", "proxy", "encoder", "runner"):
            for inherited, fallback, address in (("desktop-bus", "user-bus", "desktop-bus"), ("", "user-bus", "user-bus"), ("", "", "")):
                with self.subTest(mode=mode, inherited=inherited, fallback=fallback), \
                        patch.dict(os.environ, {"DBUS_SESSION_BUS_ADDRESS": inherited, "DBUS_SESSION_BUS_PID": "123"}, clear=True), \
                        patch("xpra.dbus.common.get_user_bus_address", return_value=fallback), \
                        patch("xpra.server.subsystem.dbus.reload_dbus_attributes") as reload, \
                        patch("xpra.server.dbus.start.start_dbus") as launch, \
                        patch("xpra.server.dbus.start.wait_for_dbus") as wait, \
                        patch("xpra.server.subsystem.dbus.save_dbus_x11_properties") as save, \
                        patch.object(features, "x11", True), \
                        patch.object(DbusManager, "init_dbus_server") as control, \
                        patch("xpra.server.subsystem.dbus.os.kill") as kill:
                    session_files = SimpleNamespace(write_session_file=Mock(), session_files=[])
                    manager = self.make_manager(mode)
                    manager.server.subsystems["session-files"] = session_files
                    manager.early_setup()
                    manager.setup()
                    manager.late_cleanup()
                    self.assertEqual(manager.env, {"DBUS_SESSION_BUS_ADDRESS": address} if address else {})
                    self.assertEqual(os.environ["DBUS_SESSION_BUS_ADDRESS"], address)
                    self.assertEqual(manager.pid, 0)
                    self.assertEqual(control.call_count, int(bool(address)))
                    reload.assert_not_called()
                    launch.assert_not_called()
                    wait.assert_not_called()
                    save.assert_not_called()
                    kill.assert_not_called()
                    session_files.write_session_file.assert_not_called()

    def test_existing_session_waits_for_bus(self):
        dbus_env = {"DBUS_SESSION_BUS_ADDRESS": "desktop-bus"}
        for mode in ("shadow", "expand"):
            with self.subTest(mode=mode), patch.dict(os.environ, {}, clear=True), \
                    patch("xpra.server.subsystem.dbus.reload_dbus_attributes") as reload, \
                    patch("xpra.server.dbus.start.start_dbus") as launch, \
                    patch("xpra.server.dbus.start.wait_for_dbus", return_value=dbus_env) as wait, \
                    patch("xpra.server.subsystem.dbus.os.kill") as kill:
                manager = self.make_manager(mode, "wait")
                manager.early_setup()
                manager.late_cleanup()
                self.assertEqual(manager.env, dbus_env)
                self.assertEqual(os.environ["DBUS_SESSION_BUS_ADDRESS"], "desktop-bus")
                wait.assert_called_once()
                reload.assert_not_called()
                launch.assert_not_called()
                kill.assert_not_called()

    def test_virtual_session_starts_bus(self):
        dbus_env = {"DBUS_SESSION_BUS_ADDRESS": "private-bus", "DBUS_SESSION_BUS_PID": "456"}
        for mode in ("seamless", "desktop", "monitor", "upgrade", "upgrade-seamless", "upgrade-desktop", "upgrade-monitor"):
            with self.subTest(mode=mode), patch.dict(os.environ, {}, clear=True), \
                    patch("xpra.server.subsystem.dbus.reload_dbus_attributes", return_value=(0, {})), \
                    patch("xpra.server.dbus.start.start_dbus", return_value=(456, dbus_env)) as launch, \
                    patch("xpra.server.subsystem.dbus.os.kill") as kill:
                manager = self.make_manager(mode)
                manager.early_setup()
                self.assertEqual(manager.env, dbus_env)
                self.assertEqual(os.environ["DBUS_SESSION_BUS_ADDRESS"], "private-bus")
                launch.assert_called_once_with("dbus-launch")
                manager.late_cleanup()
                kill.assert_called_once_with(456, signal.SIGINT)

    def test_exception_wrap(self):
        from xpra.server.dbus import common
        if not common.log.is_debug_enabled():
            common.log = FakeLogger()

        def rimporterror():
            raise ImportError()

        def rfail():
            raise Exception("test")

        def ok():
            return True

        def t(fn, r):
            v = common.dbus_exception_wrap(fn)
            assert v==r, f"expected dbus_exception_wrap({fn})={r} but got {v}"
        t(rimporterror, None)
        t(rfail, None)
        t(ok, True)

    def test_start_dbus(self):
        from xpra.server.dbus.start import start_dbus

        def f(v):
            r, d = start_dbus(v)
            assert r==0 and not d, f"dbus should not have started for {v!r}"

        def w(v):
            r, d = start_dbus(v)
            assert r>0 or d, f"dbus should have started for {v!r}, r={r} d={d}"

        def rm():
            os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        with OSEnvContext():
            rm()
            f("no")
            f("0")
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = "whatever"
            w("dbus-launch")
            rm()
            f("this-is-not-a-valid-command")
            f("shlex-parsing-error '")
            f("echo set DBUS_SESSION_BUS_PID")
            w("echo set DBUS_SESSION_BUS_PID=50")
            w("echo \"set DBUS_SESSION_BUS_PID='100';\"")
            w("echo set DBUS_SESSION_BUS_PID=150;")
            w("echo setenv DBUS_SESSION_BUS_PID 200")
            w("printf \"export DBUS_SESSION_BUS_PID\nset DBUS_SESSION_BUS_PID=250\n\"")

    def test_reload_dbus_environment(self):
        from xpra.dbus.common import find_session_bus_address
        from xpra.server.subsystem.dbus import DbusManager

        dbus_env = {
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/xpra/bus",
            "DBUS_SESSION_BUS_PID": str(os.getpid()),
            "DBUS_SESSION_BUS_WINDOWID": "42",
        }
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "dbus.pid").write_text(dbus_env["DBUS_SESSION_BUS_PID"])
            Path(directory, "dbus.env").write_text("\n".join(f"{k}={v}" for k, v in dbus_env.items()))
            for inherited_address in ("", "unix:path=/desktop/bus"):
                with self.subTest(inherited_address=inherited_address), patch.dict(os.environ, {
                    "DISPLAY": ":100",
                    "XPRA_SESSION_DIR": directory,
                    "DBUS_SESSION_BUS_ADDRESS": inherited_address,
                }, clear=True), patch("xpra.server.dbus.start.start_dbus") as launch:
                    manager = DbusManager()
                    manager.init_dbus_env()
                    # An upgraded server and its children must discover the saved private bus.
                    self.assertEqual(find_session_bus_address(), dbus_env["DBUS_SESSION_BUS_ADDRESS"])
                    self.assertEqual({k: os.environ.get(k) for k in dbus_env}, dbus_env)
                    self.assertEqual(manager.pid, os.getpid())
                    launch.assert_not_called()

    def test_session_bus_follows_address(self):
        try:
            import dbus
            assert dbus
        except ImportError:
            return
        from xpra.dbus import common as dbus_common
        from xpra.server.dbus import start
        from xpra.server.dbus.start import start_dbus
        if not start.log.is_debug_enabled():
            start.log = FakeLogger()

        def bus_id(bus) -> str:
            return str(bus.call_blocking("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "GetId", "", ()))

        saved = (dbus_common._session_bus, dbus_common._session_bus_address)
        pids = []
        ids = []
        try:
            with OSEnvContext():
                for _ in (1, 2):
                    dbus_pid, dbus_env = start_dbus("dbus-launch --sh-syntax --close-stderr")
                    address = dbus_env.get("DBUS_SESSION_BUS_ADDRESS", "")
                    if not address:
                        # no dbus-launch available?
                        return
                    pids.append(dbus_pid)
                    os.environ.update(dbus_env)
                    # we must connect to the bus from the environment,
                    # even if we were already connected to another one:
                    bus = dbus_common.init_session_bus()
                    assert dbus_common.get_session_bus_address() == address
                    ids.append(bus_id(bus))
            assert ids[0] != ids[1], f"both connections ended up on the same bus {ids[0]!r}"
        finally:
            dbus_common._session_bus, dbus_common._session_bus_address = saved
            for pid in pids:
                if pid:
                    os.kill(pid, signal.SIGINT)

    def test_save_dbus_env(self):
        from xpra.server.dbus import start
        if not start.log.is_debug_enabled():
            start.log = FakeLogger()
        with OSEnvContext():
            #assert get_saved_dbus_env()
            pass


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
