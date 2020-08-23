#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX, POSIX


def noop(*_args, **_kwargs):
    pass

class DBUSTest(unittest.TestCase):

    def test_exception_wrap(self):
        from xpra.server.dbus import dbus_common
        class FakeLogger:
            error = noop
            info = noop
            debug = noop
            def __call__(self, *args, **kwargs):
                noop(*args, **kwargs)
        dbus_common.log = FakeLogger()
        def r1():
            return 1
        def rimporterror():
            raise ImportError()
        def rfail():
            raise Exception("test")
        assert dbus_common.dbus_exception_wrap(r1)==1
        assert dbus_common.dbus_exception_wrap(rimporterror)==None
        assert dbus_common.dbus_exception_wrap(rfail)==None


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
