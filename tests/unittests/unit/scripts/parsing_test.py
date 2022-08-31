#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.log import add_debug_category, remove_debug_category
from xpra.os_util import nomodule_context, WIN32
from xpra.scripts.parsing import (
    parse_ssh_option, add_ssh_args, add_ssh_proxy_args, parse_remote_display,
    )

class TestParsing(unittest.TestCase):

    def test_ssh_parsing(self):
        assert parse_ssh_option("auto")[0] in ("paramiko", "ssh")
        assert parse_ssh_option("ssh")==["ssh"]
        assert parse_ssh_option("ssh -v")==["ssh", "-v"]
        with nomodule_context("paramiko"):
            add_debug_category("ssh")
            def pssh(s, e):
                r = parse_ssh_option(s)[0]
                assert r==e, f"expected {e} got {r}"
            if WIN32:
                pssh("auto", "plink.exe")
            else:
                pssh("auto", "ssh")
            remove_debug_category("ssh")
        #args:
        def targs(e, *args, **kwargs):
            r = add_ssh_args(*args, **kwargs)
            assert r==e, f"expected {e} but got {r}"
        targs([], None, None, None, None, None, is_paramiko=True)
        targs(["-pw", "password", "-l", "username", "-P", "2222", "-T", "host"],
              "username", "password", "host", 2222, None, is_putty=True)
        if not WIN32:
            keyfile = os.path.expanduser("~/key")
            targs(["-l", "username", "-p", "2222", "-T", "host", "-i", keyfile],
                  "username", "password", "host", 2222, keyfile)
        #ssh proxy:
        def pargs(e, n, *args, **kwargs):
            r = add_ssh_proxy_args(*args, **kwargs)[:n]
            assert r==e, f"expected {e} but got {r}"
        pargs(["-o"], 1,
            "username", "password", "host", 222, None, ["ssh"])
        pargs(["-proxycmd"], 1,
              "username", "password", "host", 222, None, ["putty.exe"], is_putty=True)
        #remote display attributes:
        assert parse_remote_display("somedisplay").get("display")=="somedisplay"
        assert parse_remote_display("10?proxy=username:password@host:222").get("proxy")=="username:password@host:222"
        def t(s):
            v = parse_remote_display(s)
            assert v.get("display")=="somedisplay"
        t("somedisplay?proxy=")
        t("somedisplay?proxy=:22")
        t("somedisplay?proxy=:@host:22")
        t("somedisplay?proxy=:password@host:22")


def main():
    unittest.main()

if __name__ == '__main__':
    main()
