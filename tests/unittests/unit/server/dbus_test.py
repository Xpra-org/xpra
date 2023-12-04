#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import OSX, POSIX
from xpra.util.env import OSEnvContext


def noop(*_args, **_kwargs):
    pass

class FakeLogger:
    error = noop
    warn = noop
    info = noop
    debug = noop
    def __call__(self, *args, **kwargs):
        noop(*args, **kwargs)

class DBUSTest(unittest.TestCase):

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
