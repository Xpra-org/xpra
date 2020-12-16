#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import shlex
import signal
import unittest
from subprocess import Popen, DEVNULL, PIPE

from xpra.log import add_debug_category, remove_debug_category
from xpra.os_util import OSEnvContext, pollwait, nomodule_context, WIN32, POSIX, OSX
from xpra.util import AdHocStruct
from xpra.platform.paths import get_xpra_command
from xpra.scripts.main import (
    nox, noerr,
    use_systemd_run, systemd_run_command, systemd_run_wrap,
    isdisplaytype,
    check_display,
    get_host_target_string,
    parse_display_name, find_session_by_name,
    parse_ssh_string, add_ssh_args, add_ssh_proxy_args, parse_proxy_attributes,
    connect_to,
    )

class TestMain(unittest.TestCase):

    def test_nox(self):
        with OSEnvContext():
            os.environ["DISPLAY"] = "not-a-display"
            nox()
            assert os.environ.get("DISPLAY") is None

    def test_systemd_run(self):
        for s in ("yes", "no", "auto"):
            if not use_systemd_run(s):
                continue
            for user in (True, False):
                for systemd_run_args in ("", "-d"):
                    assert systemd_run_command("mode", systemd_run_args, user=user)[0]=="systemd-run"
            with OSEnvContext():
                os.environ["XPRA_LOG_SYSTEMD_WRAP"] = "0"
                assert systemd_run_wrap("unused", ["xpra", "--version"], stdout=DEVNULL, stderr=DEVNULL)==0

    def test_display_type_check(self):
        for arg in ("ssh:host", "ssh/host", "tcp:IP", "ssl/host", "vsock:port"):
            args = [arg]
            assert isdisplaytype(args, "ssh", "tcp", "ssl", "vsock")

    def test_check_display(self):
        #only implemented properly on MacOS
        check_display()


    def test_host_parsing(self):
        try:
            target = get_host_target_string({})
        except Exception:
            pass
        else:
            raise Exception("got host string '%s' without specifying any display attributes!" % target)
        def t(d, e):
            s = get_host_target_string(d)
            assert s==e, "expected '%s' for %s but got '%s'" % (e, d, s)
        t({"type" : "ssh", "username" : "foo", "host" : "bar"}, "ssh://foo@bar/")
        t({"type" : "ssh", "username" : "foo", "host" : "bar", "port" : -1}, "ssh://foo@bar/")
        t({"type" : "ssh", "username" : "foo", "host" : "bar", "port" : 2222}, "ssh://foo@bar:2222/")

    def test_parse_display_name(self):
        opts = AdHocStruct()
        opts.socket_dirs = ["/tmp"]
        opts.socket_dir = "/tmp"
        opts.exit_ssh = False
        opts.ssh = "ssh -v "
        opts.remote_xpra = "run-xpra"
        if WIN32:
            fd = parse_display_name(None, opts, "named-pipe://FOO")["named-pipe"]
            sd = parse_display_name(None, opts, "FOO")["named-pipe"]
        else:
            fd = parse_display_name(None, opts, "socket:///FOO")
            sd = parse_display_name(None, opts, "/FOO")
        assert sd==fd, "expected %s but got %s" % (fd, sd)
        def t(s, e):
            r = parse_display_name(None, opts, s)
            if e:
                for k,v in e.items():
                    actual = r.get(k)
                    assert actual==v, "expected %s but got %s from parse_display_name(%s)=%s" % (v, actual, s, r)
        def e(s):
            try:
                parse_display_name(None, opts, s)
            except Exception:
                pass
            else:
                raise Exception("parse_display_name should fail for %s" % s)
        if POSIX:
            e("ZZZZZZ")
            t("10", {"display_name" : "10", "local" : True, "type" : "unix-domain"})
            t("/tmp/thesocket", {"display_name" : "socket:///tmp/thesocket"})
            t("socket:/tmp/thesocket", {"display_name" : "socket:/tmp/thesocket"})
        e("tcp://host:NOTANUMBER/")
        e("tcp://host:0/")
        e("tcp://host:65536/")
        t("tcp://username@host/", {"username" : "username", "password" : None})
        for socktype in ("tcp", "udp", "ws", "wss", "ssl", "ssh"):
            #e(socktype+"://a/b/c/d")
            t(socktype+"://username:password@host:10000/DISPLAY?key1=value1", {
                "type"      : socktype,
                "display"   : "DISPLAY",
                "key1"      : "value1",
                "username"  : "username",
                "password"  : "password",
                "port"      : 10000,
                "host"      : "host",
                "local"     : False,
                })
        t("tcp://fe80::c1:ac45:7351:ea69:14500", {"host" : "fe80::c1:ac45:7351:ea69", "port" : 14500})
        t("tcp://fe80::c1:ac45:7351:ea69%eth1:14500", {"host" : "fe80::c1:ac45:7351:ea69%eth1", "port" : 14500})
        t("tcp://[fe80::c1:ac45:7351:ea69]:14500", {"host" : "fe80::c1:ac45:7351:ea69", "port" : 14500})
        t("tcp://host/100,key1=value1", {"key1" : "value1"})
        t("tcp://host/key1=value1", {"key1" : "value1"})
        try:
            from xpra.net.vsock import CID_ANY, PORT_ANY    #@UnresolvedImport
            t("vsock://any:any/", {"vsock" : (CID_ANY, PORT_ANY)})
            t("vsock://10:2000/", {"vsock" : (10, 2000)})
        except ImportError:
            pass


    def test_find_session_by_name(self):
        opts = AdHocStruct()
        opts.socket_dirs = ["/tmp"]
        opts.socket_dir = "/tmp"
        assert find_session_by_name(opts, "not-a-valid-session") is None


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
            targs(["-l", "username", "-p", "2222", "-T", "host", "-i", "/tmp/key"],
                  "username", "password", "host", 2222, "/tmp/key")
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

    def test_connect_to(self):
        def f(**kwargs):
            fd(kwargs)
        def fd(d):
            opts = AdHocStruct()
            try:
                #silence errors since we're expecting them:
                from xpra.scripts import main as xpra_main
                try:
                    saved_timeout = xpra_main.CONNECT_TIMEOUT
                    xpra_main.CONNECT_TIMEOUT = 5
                    saved_werr = xpra_main.werr
                    xpra_main.werr = main.noop
                    conn = connect_to(d, opts)
                finally:
                    xpra_main.werr = saved_werr
                    xpra_main.CONNECT_TIMEOUT = saved_timeout
            except Exception:
                #from xpra.util import get_util_logger
                #get_util_logger().error("connect_to(%s, %s)", d, opts, exc_info=True)
                pass
            else:
                try:
                    conn.close()
                except Exception:
                    pass
                raise Exception("connect_to(%s) should have failed" % (d,))
        #without extra arguments to specify the endpoint,
        #all connections should fail, even if they have a valid type:
        f(type="invalid", display_name="test")
        f(type="vsock", display_name="test", vsock=(10, 1000))
        fd({"type" : "named-pipe", "display_name" : "test", "named-pipe" : "TEST-INVALID"})
        f(type="unix-domain", display_name=":100000", display="100000")
        for socktype in ("tcp", "ssl", "ws", "wss", ):
            f(type=socktype, display_name="test", host="localhost", port=100000)
        for paramiko in (True, False):
            f(type="ssh", display_name="test", host="localhost", port=100000, is_paramiko=paramiko)
        fd({
            "type"              : "ssl",
            "display_name"      : "test",
            "host"              : "localhost",
            "port"              : 100000,
            "strict-host-check" : False,
            })
        #udp never fails when opening the connection:
        conn = connect_to({"type" : "udp", "host" : "localhost", "port" : 20000, "display_name" : ":200"}, AdHocStruct())
        conn.close()


    def _test_subcommand(self, args, timeout=60, **kwargs):
        proc = self._run_subcommand(args, timeout, **kwargs)
        if proc.poll() is None:
            proc.terminate()
            raise Exception("%s did not terminate after %i seconds" % (args, timeout))

    def _run_subcommand(self, args, wait=60, **kwargs):
        cmd = get_xpra_command()+shlex.split(args)
        if "stdout" not in kwargs:
            kwargs["stdout"] = DEVNULL
        if "stderr" not in kwargs:
            kwargs["stderr"] = DEVNULL
        try:
            proc = Popen(cmd, **kwargs)
            pollwait(proc, wait)
            return proc
        except Exception:
            raise Exception("failed on %s" % (cmd,))

    def test_nongui_subcommands(self):
        for args in (
            "initenv",
            "list",
            "list-windows",
            "showconfig",
            "showsetting xvfb",
            "encoding",
            "webcam",
            "keyboard",
            "keymap",
            "gui-info",
            "network-info",
            "path-info",
            "printing-info",
            "version-info",
            "gtk-info",
            "opengl", "opengl-probe",
            "help",
            "whatever --help",
            "start --speaker-codec=help",
            "start --microphone-codec=help",
            "attach --speaker-codec=help",
            "attach --microphone-codec=help",
            "_sound_query",
            "invalid-command",
            ):
            self._test_subcommand(args)

    def test_terminate_subcommands(self):
        if POSIX and not OSX:
            #can't test commands that require a display yet
            return
        subcommands = [
            "mdns-gui",
            "sessions",
            "launcher",
            "gui",
            "bug-report",
            "_dialog",
            "_pass",
            #"send-file", needs a server socket
            #"splash", has its own test module
            "clipboard-test",
            "keyboard-test",
            "toolbox",
            "colors-test",
            "colors-gradient-test",
            "transparent-colors",
            ]
        for args in subcommands:
            proc = self._run_subcommand(args, 10, stdout=PIPE, stderr=PIPE)
            r = proc.poll()
            if r is not None:
                raise Exception("%s subcommand should not have terminated" % (args,))
            noerr(proc.send_signal, signal.SIGTERM)
            if pollwait(proc, 2) is None:
                noerr(proc.terminate)
                if pollwait(proc, 2) is None:
                    noerr(proc.kill)

    def test_debug_option(self):
        for debug in ("all", "util", "platform,-import", "foo,,bar"):
            args = "version-info --debug %s" % debug
            self._test_subcommand(args, 20)

    def test_misc_env_switches(self):
        with OSEnvContext():
            os.environ["XPRA_NOMD5"] = "1"
            self._test_subcommand("version-info")


def main():
    unittest.main()

if __name__ == '__main__':
    main()
