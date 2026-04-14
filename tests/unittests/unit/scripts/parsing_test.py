#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

from xpra.os_util import WIN32, POSIX, OSX
from xpra.util.env import nomodule_context
from xpra.scripts.parsing import (
    parse_ssh_option, get_ssh_args, get_ssh_proxy_args,
    audio_option, parse_env, parse_URL, _sep_pos, normalize_display_name,
    parse_display_name, parse_cmdline,
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


class TestAudioOption(unittest.TestCase):

    def test_no_returns_disabled(self):
        self.assertEqual(audio_option("no"), "disabled")

    def test_yes_returns_on(self):
        self.assertEqual(audio_option("yes"), "on")

    def test_false_returns_off(self):
        self.assertEqual(audio_option("false"), "off")

    def test_disabled_returns_disabled(self):
        self.assertEqual(audio_option("disabled"), "disabled")

    def test_on_returns_on(self):
        self.assertEqual(audio_option("on"), "on")


class TestParseEnv(unittest.TestCase):

    def test_basic(self):
        result = parse_env(["FOO=bar", "BAZ=qux"])
        self.assertEqual(result["FOO"], "bar")
        self.assertEqual(result["BAZ"], "qux")

    def test_comment_skipped(self):
        result = parse_env(["#COMMENTED=out", "REAL=value"])
        self.assertNotIn("COMMENTED", result)
        self.assertEqual(result["REAL"], "value")

    def test_missing_equals_skipped(self):
        result = parse_env(["NOEQUALS"])
        self.assertEqual(result, {})

    def test_multiple_equals_splits_on_first(self):
        result = parse_env(["K=a=b=c"])
        self.assertEqual(result["K"], "a=b=c")

    def test_empty_value(self):
        result = parse_env(["EMPTY="])
        self.assertEqual(result["EMPTY"], "")


class TestParseURL(unittest.TestCase):

    def test_tcp_with_params(self):
        address, opts = parse_URL("tcp://host:10000?compression_level=1")
        self.assertIn("host:10000", address)
        # compression_level is typed as int in OPTION_TYPES
        self.assertEqual(opts.get("compression_level"), 1)

    def test_no_params(self):
        address, opts = parse_URL("tcp://host:10000")
        self.assertEqual(opts, {})
        self.assertIn("host:10000", address)

    def test_xpra_prefix_stripped(self):
        address, opts = parse_URL("xpra+tcp://host:10000")
        self.assertIn("host:10000", address)

    def test_path_included(self):
        address, opts = parse_URL("socket:///tmp/mysocket")
        self.assertIn("/tmp/mysocket", address)


class TestSepPos(unittest.TestCase):

    def test_colon_only(self):
        self.assertEqual(_sep_pos("host:10"), 4)

    def test_slash_only(self):
        self.assertEqual(_sep_pos("path/to"), 4)

    def test_colon_before_slash(self):
        self.assertEqual(_sep_pos("host:10/path"), 4)

    def test_slash_before_colon(self):
        self.assertEqual(_sep_pos("path/host:10"), 4)

    def test_neither(self):
        self.assertEqual(_sep_pos("hostname"), -1)


class TestNormalizeDisplayName(unittest.TestCase):

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            normalize_display_name("")

    def test_at_prefix_returned_as_is(self):
        result = normalize_display_name("@mysocket")
        self.assertEqual(result, "@mysocket")

    @unittest.skipUnless(POSIX and not OSX, "POSIX only")
    def test_absolute_path_gets_socket_scheme(self):
        result = normalize_display_name("/tmp/xpra.sock")
        self.assertEqual(result, "socket:///tmp/xpra.sock")

    def test_display_number_gets_colon(self):
        if POSIX:
            result = normalize_display_name("10")
            self.assertEqual(result, ":10")

    def test_url_passthrough(self):
        result = normalize_display_name("tcp://host:10000")
        self.assertIn("host:10000", result)


def _make_opts():
    """Return a minimal opts struct for parse_display_name."""
    from xpra.scripts.parsing import make_defaults_struct
    return make_defaults_struct()


@unittest.skipIf(WIN32, "not supported on Windows")
class TestParseDisplayNameSocket(unittest.TestCase):

    def test_abstract_socket(self):
        if WIN32:
            return
        opts = _make_opts()
        desc = parse_display_name(lambda msg: None, opts, "@mysocket")
        self.assertEqual(desc["type"], "socket")
        self.assertTrue(desc["local"])
        self.assertIn("socket_path", desc)


class TestParseDisplayNameSsh(unittest.TestCase):

    def test_ssh_without_display(self):
        opts = _make_opts()
        desc = parse_display_name(lambda msg: None, opts, "ssh://somehost")
        self.assertEqual(desc["type"], "ssh")
        self.assertEqual(desc["host"], "somehost")
        # no display specified → no "display" key in desc
        self.assertFalse(desc.get("display"))

    def test_ssh_with_display(self):
        opts = _make_opts()
        desc = parse_display_name(lambda msg: None, opts, "ssh://somehost/10")
        self.assertEqual(desc["type"], "ssh")
        self.assertEqual(desc["host"], "somehost")
        self.assertEqual(desc.get("display"), "10")
        self.assertIn("10", desc.get("display_as_args", []))


@unittest.skipUnless(POSIX and not OSX, "vsock only available on Linux")
class TestParseDisplayNameVsock(unittest.TestCase):

    def _mock_vsock(self):
        vsock_mod = MagicMock()
        vsock_mod.PORT_ANY = 0xFFFFFFFF
        vsock_mod.CID_ANY = 0xFFFFFFFF
        vsock_mod.STR_TO_CID = {"HOST": 2, "HYPERVISOR": 0}
        return vsock_mod

    def test_vsock_numeric(self):
        vsock_mod = self._mock_vsock()
        with patch.dict(sys.modules, {"xpra.net.vsock.vsock": vsock_mod}):
            opts = _make_opts()
            desc = parse_display_name(lambda msg: None, opts, "vsock://3:5000")
        self.assertEqual(desc["type"], "vsock")
        cid, port = desc["vsock"]
        self.assertEqual(cid, 3)
        self.assertEqual(port, 5000)

    def test_vsock_any_port(self):
        vsock_mod = self._mock_vsock()
        with patch.dict(sys.modules, {"xpra.net.vsock.vsock": vsock_mod}):
            opts = _make_opts()
            desc = parse_display_name(lambda msg: None, opts, "vsock://3")
        self.assertEqual(desc["type"], "vsock")
        _cid, port = desc["vsock"]
        self.assertEqual(port, vsock_mod.PORT_ANY)


@unittest.skipUnless(not WIN32, "not on Windows")
class TestParseDisplayNameHyperV(unittest.TestCase):

    def _mock_hyperv(self):
        # provide the HV_GUID_* attributes on the real socket module
        import socket as _socket
        patches = {}
        for attr in ("HV_GUID_ZERO", "HV_GUID_BROADCAST", "HV_GUID_CHILDREN",
                     "HV_GUID_LOOPBACK", "HV_GUID_PARENT"):
            if not hasattr(_socket, attr):
                patches[attr] = f"00000000-0000-0000-0000-{attr[-6:].lower():0>12}"
        return patches

    def test_hyperv_loopback(self):
        import socket as _socket
        socket_patches = self._mock_hyperv()
        common_mock = MagicMock()
        common_mock.verify_hyperv_available = MagicMock()
        with patch.dict(sys.modules, {"xpra.net.common": common_mock}):
            with patch.multiple(_socket, **socket_patches, create=True):
                opts = _make_opts()
                desc = parse_display_name(lambda msg: None, opts, "hyperv://loopback:20000")
        self.assertEqual(desc["type"], "hyperv")
        vmid, service = desc["hyperv"]
        self.assertIsNotNone(vmid)
        self.assertIsNotNone(service)


class TestParseCmdlineMinimal(unittest.TestCase):

    def test_minimal_flag_sets_defaults(self):
        options, args = parse_cmdline(["xpra", "attach", "--minimal", "tcp://host:10000"])
        # minimal mode disables features; some are stored as bool, others as "no"/"off" string
        from xpra.util.parsing import FALSE_OPTIONS

        def is_disabled(v):
            return not v or str(v).lower() in FALSE_OPTIONS
        self.assertTrue(is_disabled(options.audio))
        self.assertTrue(is_disabled(options.video))
        self.assertTrue(is_disabled(options.mmap))
        self.assertTrue(is_disabled(options.clipboard))
        self.assertTrue(is_disabled(options.opengl))

    def test_minimal_preserves_explicit_overrides(self):
        # explicit value on cmdline should survive the second parse pass
        options, args = parse_cmdline(["xpra", "attach", "--minimal", "--opengl=yes", "tcp://host:10000"])
        self.assertEqual(options.opengl, "yes")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
