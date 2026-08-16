#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import signal
import unittest
from unittest.mock import patch

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

    def test_schedule_dbus_x11_properties(self):
        from xpra.server.subsystem.dbus import (
            save_dbus_x11_properties,
            schedule_dbus_x11_properties,
        )
        dbus_env = {"DBUS_SESSION_BUS_PID": "123"}
        with patch("xpra.os_util.gi_import") as gi_import:
            schedule_dbus_x11_properties(dbus_env)
        gi_import.assert_called_once_with("GLib")
        gi_import.return_value.idle_add.assert_called_once_with(save_dbus_x11_properties, dbus_env)

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
