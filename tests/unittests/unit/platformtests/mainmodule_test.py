#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.platform import (
    platform_import,
    init, clean, threaded_server_init,
    program_context,
    set_default_name, set_prgname,
    #set_name, set_prgname, set_application_name,
    get_prgname,
    get_application_name,
    command_error, command_info,
    )
from xpra.make_thread import start_thread
from xpra.scripts import main as xpra_main
from xpra.os_util import WIN32


class PlatformInfoTest(unittest.TestCase):

    def test_all(self):
        set_default_name("platform info test", "platform-info-test")
        init()
        t = start_thread(threaded_server_init, "server-init")
        t.join()
        with program_context() as p:
            assert repr(p)
            assert get_application_name()=="platform-info-test"
            assert get_prgname()=="platform info test"

        if WIN32:   # pragma: no cover
            #we can check for command_error and command_info
            #on win32 because those trigger dialogs
            return
        calls = []
        def ccall(*args):
            calls.append(args)
        xpra_main.error = ccall
        xpra_main.info = ccall
        command_error("error")
        command_info("info")
        assert len(calls)==2, "expected 2 messages but got: %s" % (calls,)
        set_prgname(None)
        clean()

    def test_fail_import(self):
        where = {}
        platform_import(where, "invalid name", False, "foo")
        def f(*args):
            try:
                platform_import(where, *args)
            except ImportError:
                pass
            else:
                raise Exception("should have failed to import invalid name")
        f("invalid name", True, "bar")
        #test with some valid platform modules:
        # - required import is missing:
        f("paths", True, "this-function-does-not-exist")
        where = {}
        # - optional import is missing:
        platform_import(where, "paths", False, "do_get_app_dir", "optional-function")
        assert len(where)==1, "where=%s" % (where,)

def main():
    unittest.main()

if __name__ == '__main__':
    main()
