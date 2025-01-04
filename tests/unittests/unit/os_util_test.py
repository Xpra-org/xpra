#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import (
    POSIX,
    getuid, getgid, get_shell_for_uid, get_username_for_uid, get_home_for_uid,
    get_hex_uuid, get_int_uuid, get_user_uuid,
)
from xpra.util.env import OSEnvContext
from xpra.util.thread import is_main_thread
from xpra.util.io import livefds
from xpra.util.system import (
    is_Ubuntu, is_Debian, is_unity,
    is_gnome, is_kde, is_WSL,
)
from xpra.util.str_fn import strtobytes, bytestostr, hexstr, memoryview_to_bytes


class TestOSUtil(unittest.TestCase):

    def check(self, str_value):
        b = strtobytes(str_value)
        assert b
        s = bytestostr(b)
        assert s
        assert s==str_value
        if not memoryview:
            return
        mv = memoryview(b)
        mvb = memoryview_to_bytes(mv)
        mvs = bytestostr(mvb)
        assert mvs==str_value

    def test_livefds(self):
        assert len(livefds())>=2

    def test_distribution_variant(self):
        is_Ubuntu()
        is_Debian()
        is_WSL()

    def test_de(self):
        is_unity()
        is_gnome()
        is_kde()

    def test_uuid(self):
        assert len(get_hex_uuid())==32
        assert isinstance(get_int_uuid(), int)
        assert get_int_uuid()!=0
        assert get_user_uuid()!=0

    def test_posix_wrappers(self):
        if not POSIX:
            return
        assert isinstance(getuid(), int)
        assert isinstance(getgid(), int)
        def isstr(v):
            assert v
            assert isinstance(v, str)
        isstr(get_shell_for_uid(getuid()))
        isstr(get_username_for_uid(getuid()))
        isstr(get_home_for_uid(getuid()))
        assert not get_shell_for_uid(999999999)


    def test_memoryview_to_bytes(self):
        assert memoryview_to_bytes(b"bar")==b"bar"
        assert memoryview_to_bytes(memoryview(b"foo"))==b"foo"
        assert memoryview_to_bytes(bytearray(b"foo"))==b"foo"
        assert memoryview_to_bytes(u"foo")==b"foo"

    def test_hexstr(self):
        assert hexstr("01")=="3031"

    def test_bytes(self):
        assert strtobytes(b"hello")==b"hello"

    def test_strs(self):
        assert bytestostr(u"foo")==u"foo"
        for l in (1, 16, 255):
            zeroes  = chr(0)*l
            ones    = chr(1)*l
            ff      = chr(255)*l
            fe      = chr(254)*l
            self.check(zeroes)
            self.check(ones)
            self.check(ff)
            self.check(fe)

    def test_env_context(self):
        import os
        env = os.environ.copy()
        with OSEnvContext():
            os.environ["foo"] = "bar"
        assert os.environ.get("foo")!="bar"
        assert os.environ==env

    def test_is_main_thread(self):
        assert is_main_thread()
        result = []
        def notmainthread():
            result.append(is_main_thread())
        from threading import Thread
        t = Thread(target=notmainthread)
        t.start()
        t.join()
        assert len(result)==1
        assert result[0] is False


def main():
    unittest.main()

if __name__ == '__main__':
    main()
