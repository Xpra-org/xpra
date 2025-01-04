#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.os_util import WIN32
from xpra.util.env import nomodule_context
from xpra.scripts.parsing import (
    parse_ssh_option, get_ssh_args, get_ssh_proxy_args, parse_remote_display,
)


class TestParsing(unittest.TestCase):

    def test_ssh_parsing(self):
        assert parse_ssh_option("auto")[0] in ("paramiko", "ssh")
        assert parse_ssh_option("ssh") == ["ssh"]
        assert parse_ssh_option("ssh -v") == ["ssh", "-v"]
        with nomodule_context("paramiko"):
            def pssh(s, e):
                r = parse_ssh_option(s)[0]
                assert r == e, f"expected {e} got {r}"

            if WIN32:
                pssh("auto", "plink.exe")
            else:
                pssh("auto", "ssh")

        # args:
        def targs(e, *args):
            r = get_ssh_args(*args)
            assert r == e, f"expected {e} but got {r}"

        targs([], {"host": "host"})
        targs(["-pw", "password1", "-l", "username1", "-P", "2222", "-T", "host1"], {
            "username": "username1",
            "password": "password1",
            "host": "host1",
            "port": 2222,
        }, ["putty"])
        if not WIN32:
            keyfile = os.path.expanduser("~/key")
            targs(["-l", "username1", "-p", "2222", "-T", "host1", "-i", keyfile], {
                "username": "username1",
                "password": "password1",
                "host": "host1",
                "port": 2222,
                "key": keyfile,
            }, ["ssh"])

        # ssh proxy:
        def pargs(e, n, *args):
            r = get_ssh_proxy_args(*args)[:n]
            assert r == e, f"expected {e} but got {r}"

        pargs(["-o"], 1, {
            "proxy_username": "username1",
            "proxy_password": "password1",
            "proxy_host": "host1",
            "proxy_port": 2222,
        }, ["ssh"])
        pargs(["-proxycmd"], 1, {
            "proxy_username": "username1",
            "proxy_password": "password1",
            "proxy_host": "host1",
            "proxy_port": 2222,
        }, ["plink"])
        # remote display attributes:
        assert parse_remote_display("somedisplay").get("display") == "somedisplay"
        assert parse_remote_display("10?proxy=username:password@host:222").get("proxy") == "username:password@host:222"

        def t(s):
            v = parse_remote_display(s)
            assert v.get("display") == "somedisplay"

        t("somedisplay?proxy=")
        t("somedisplay?proxy=:22")
        t("somedisplay?proxy=:@host:22")
        t("somedisplay?proxy=:password@host:22")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
