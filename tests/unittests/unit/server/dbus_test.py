#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import OSX, POSIX, OSEnvContext


def noop(*_args, **_kwargs):
    pass

class FakeLogger:
    error = noop
    info = noop
    debug = noop
    def __call__(self, *args, **kwargs):
        noop(*args, **kwargs)

class DBUSTest(unittest.TestCase):

    def test_exception_wrap(self):
        from xpra.server.dbus import dbus_common
        dbus_common.log = FakeLogger()
        def r1():
            return 1
        def rimporterror():
            raise ImportError()
        def rfail():
            raise Exception("test")
        def ok():
            return True
        def t(fn, r):
            v = dbus_common.dbus_exception_wrap(fn)
            assert v==r, "expected dbus_exception_wrap(%s)=%s but got %s" % (fn, r, v)
        t(rimporterror, None)
        t(rfail, None)
        t(ok, True)


    def test_start_dbus(self):
        from xpra.server.dbus.dbus_start import start_dbus
        def f(v):
            r, d = start_dbus(v)
            assert r==0 and not d, "dbus should not have started for '%s'" % v
        def w(v):
            r, d = start_dbus(v)
            assert r>0 and d, "dbus should have started for '%s'" % v
        def rm():
            os.environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        with OSEnvContext():
            rm()
            f("no")
            f("0")
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = "whatever"
            f("dbus-launch")
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
        from xpra.server.dbus import dbus_start
        dbus_start.log = FakeLogger()
        with OSEnvContext():
            #assert get_saved_dbus_env()
            pass


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
