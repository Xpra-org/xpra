#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.log import add_debug_category, remove_debug_category
from xpra.os_util import nomodule_context, WIN32
from xpra.scripts.parsing import (
    parse_ssh_string, add_ssh_args, add_ssh_proxy_args, parse_proxy_attributes,
    )

class TestParsing(unittest.TestCase):

    def test_ssh_parsing(self):
        assert parse_ssh_string("auto")[0] in ("paramiko", "ssh")
        assert parse_ssh_string("ssh")==["ssh"]
        assert parse_ssh_string("ssh -v")==["ssh", "-v"]
        with nomodule_context("paramiko"):
            add_debug_category("ssh")
            def pssh(s, e):
                r = parse_ssh_string(s)[0]
                assert r==e, "expected %s got %s" % (e, r)
            if WIN32:
                pssh("auto", "plink.exe")
            else:
                pssh("auto", "ssh")
            remove_debug_category("ssh")
        #args:
        def targs(e, *args, **kwargs):
            r = add_ssh_args(*args, **kwargs)
            assert r==e, "expected %s but got %s" % (e, r)
        targs([], None, None, None, None, None, is_paramiko=True)
        targs(["-pw", "password", "-l", "username", "-P", "2222", "-T", "host"],
              "username", "password", "host", 2222, None, is_putty=True)
        if not WIN32:
            keyfile = os.path.expanduser("~/key")
            targs(["-l", "username", "-p", "2222", "-T", "host", "-i", keyfile],
                  "username", "password", "host", 2222, keyfile)
        #proxy:
        def pargs(e, n, *args, **kwargs):
            r = add_ssh_proxy_args(*args, **kwargs)[:n]
            assert r==e, "expected %s but got %s" % (e, r)
        pargs(["-o"], 1,
            "username", "password", "host", 222, None, ["ssh"])
        pargs(["-proxycmd"], 1,
              "username", "password", "host", 222, None, ["putty.exe"], is_putty=True)
        #proxy attributes:
        assert parse_proxy_attributes("somedisplay")==("somedisplay", {})
        attr = parse_proxy_attributes("10?proxy=username:password@host:222")[1]
        assert attr=={"proxy_host" : "host", "proxy_port" : 222, "proxy_username" : "username", "proxy_password" : "password"}
        def f(s):
            v = parse_proxy_attributes(s)
            assert v[1]=={}, "parse_proxy_attributes(%s) should fail" % s
        f("somedisplay?proxy=")
        f("somedisplay?proxy=:22")
        f("somedisplay?proxy=:@host:22")
        f("somedisplay?proxy=:password@host:22")


def main():
    unittest.main()

if __name__ == '__main__':
    main()
