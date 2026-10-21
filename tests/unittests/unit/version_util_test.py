#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

import xpra
from xpra.util import version
from xpra.os_util import POSIX
from xpra.net.common import FULL_INFO
from xpra.util.version import (
    version_compat_check, protocol_compat_check, min_version_check,
    get_host_info, get_version_info, get_platform_info,
)


class TestVersionUtilModule(unittest.TestCase):

    def test_version_compat_check_invalid(self):
        from xpra import __version__
        self.assertIsNone(version_compat_check(__version__))
        self.assertIsNotNone(version_compat_check("0.1"))

    def test_version_compat_check_minimum(self):
        from xpra.net.common import BACKWARDS_COMPATIBLE, MIN_PROTOCOL_VERSION
        self.assertEqual(MIN_PROTOCOL_VERSION, (7, 0) if BACKWARDS_COMPATIBLE else (8, 0))
        # v6 is too old:
        self.assertIsNotNone(version_compat_check("6.5.5"))
        # v7 is only supported in backwards compatible mode:
        self.assertEqual(version_compat_check("7.0") is None, BACKWARDS_COMPATIBLE)

    def test_protocol_compat_check(self):
        from xpra import __version_info__
        from xpra.net.common import MIN_PROTOCOL_VERSION
        # we are always compatible with ourselves:
        self.assertFalse(protocol_compat_check(__version_info__))
        # we must satisfy the minimum version we expose to our peers:
        self.assertFalse(protocol_compat_check(MIN_PROTOCOL_VERSION))
        # peers that don't expose a minimum `protocol-version` are older than v7:
        for missing in ("", ()):
            self.assertFalse(protocol_compat_check(missing))
        # we must honour the minimum version required by the remote end,
        # which is never truncated:
        newer = __version_info__[:-1] + (__version_info__[-1] + 1, )
        self.assertTrue(protocol_compat_check(newer))
        self.assertTrue(protocol_compat_check(tuple(__version_info__) + (1, )))
        # invalid versions are rejected rather than causing errors:
        self.assertTrue(protocol_compat_check("%i.%ibeta" % __version_info__[:2]))

    def test_min_version_check(self):
        for remote_version in ("8.0", "8.0.1", "8.1", "9", "8"):
            self.assertFalse(min_version_check(remote_version, (8, 0)), f"{remote_version!r} should satisfy 8.0")
        for remote_version in ("7.0", "7.9.9", "7", "", "invalid", "8.0beta"):
            self.assertTrue(min_version_check(remote_version, (8, 0)), f"{remote_version!r} should not satisfy 8.0")

    def test_get_host_info(self):
        attrs = []
        if POSIX and FULL_INFO:
            attrs += ["uid", "gid"]
        for x in attrs:
            self.assertTrue(x in get_host_info(), "%s not found in host info" % x)

    def test_get_version_info(self):
        for x in ("version", "revision"):
            self.assertTrue(x in get_version_info(), "%s not found in version info" % x)

    def test_get_platform_info(self):
        for x in ("release", "name"):
            self.assertTrue(x in get_platform_info(), "%s not found in platform info" % x)


class TestVersionUpdates(unittest.TestCase):

    def test_version_response_decoding_and_failures(self):
        context = object()
        with patch("ssl.create_default_context", return_value=context) as create_context, \
                patch("urllib.request.urlopen") as urlopen, patch.object(version, "get_util_logger"):
            for response, expected in ((b"8.1.2\r\n", (8, 1, 2)), (b"bad", ()), (b"", ())):
                with self.subTest(response=response):
                    urlopen.return_value.read.return_value = response
                    self.assertEqual(version.get_version_from_url("https://example.test/version"), expected)
            urlopen.assert_called_with("https://example.test/version", context=context)
            create_context.assert_called_with(cafile=version.SSL_CAFILE)
            for error in (HTTPError("url", 404, "missing", {}, None), HTTPError("url", 500, "failed", {}, None), OSError("offline")):
                with self.subTest(error=error):
                    urlopen.side_effect = error
                    self.assertEqual(version.get_version_from_url("https://example.test/version"), ())
        with patch.dict(sys.modules, {"urllib.request": None}):
            self.assertEqual(version.get_version_from_url("https://example.test/version"), ())

    def test_branch_platform_and_architecture_fallback_order(self):
        with patch.multiple(version, CHECK_SSL=True, XPRA_VERSION="8.0"), \
                patch.object(version, "get_branch", return_value="v8.0.x"), \
                patch.object(version, "get_platform_info", return_value={"machine": "x86_64"}), \
                patch.object(version.sys, "platform", "linux"), \
                patch.object(version, "get_version_from_url", return_value=()) as fetch:
            self.assertEqual(version.get_latest_version(), ())
            self.assertEqual([call.args[0] for call in fetch.call_args_list], [
                "https://xpra.org/CURRENT_VERSION_v8_0_linux_x86_64?8.0",
                "https://xpra.org/CURRENT_VERSION_v8_0_linux?8.0",
                "https://xpra.org/CURRENT_VERSION_v8_0?8.0",
                "https://xpra.org/CURRENT_VERSION_v8_linux_x86_64?8.0",
                "https://xpra.org/CURRENT_VERSION_v8_linux?8.0",
                "https://xpra.org/CURRENT_VERSION_v8?8.0",
                "https://xpra.org/CURRENT_VERSION_linux_x86_64?8.0",
                "https://xpra.org/CURRENT_VERSION_linux?8.0",
                "https://xpra.org/CURRENT_VERSION?8.0",
            ])
            fetch.reset_mock()
            fetch.side_effect = [(), (8, 1)]
            self.assertEqual(version.get_latest_version(), (8, 1))
            self.assertEqual(fetch.call_count, 2)

    def test_master_branch_and_http_override(self):
        with patch.multiple(version, CHECK_SSL=False, XPRA_VERSION="8.0"), \
                patch.object(version, "get_branch", return_value="master"), \
                patch.object(version, "get_platform_info", return_value={"machine": "arm64"}), \
                patch.object(version.sys, "platform", "darwin"), \
                patch.object(version, "get_version_from_url", return_value=(8, 1)) as fetch:
            self.assertEqual(version.get_latest_version(), (8, 1))
            fetch.assert_called_once_with("http://xpra.org/CURRENT_VERSION_OSX_arm64?8.0")

    def test_update_results_and_forced_update(self):
        with patch.object(version, "XPRA_NUMERIC_VERSION", (8, 0)), \
                patch.dict(os.environ, {"XPRA_FAKE_NEW_VERSION": "0"}), \
                patch.object(version, "get_latest_version") as latest:
            for remote, expected in (((), None), ((7, 9), False), ((8, 0), False), ((8, 1), (8, 1))):
                with self.subTest(remote=remote):
                    latest.return_value = remote
                    self.assertEqual(version.version_update_check(), expected)
            latest.return_value = (8, 0)
            os.environ["XPRA_FAKE_NEW_VERSION"] = "1"
            self.assertEqual(version.version_update_check(), (8, 0))


class TestVersionMetadata(unittest.TestCase):

    def test_revision_and_build_formatting(self):
        source = SimpleNamespace(REVISION=123, LOCAL_MODIFICATIONS=2, BRANCH="master", COMMIT="abcd")
        build = SimpleNamespace(build={"type": "light", "python": "3.14.8", "date": "2026-10-21"}, lib_test="1.2")
        with patch.dict(sys.modules, {"xpra.src_info": source, "xpra.build_info": build}), \
                patch.object(xpra, "build_info", build, create=True), \
                patch.dict(os.environ, {"XPRA_CURRENT_VERSION_BRANCH": ""}):
            self.assertEqual(version.get_branch(), "master")
            self.assertEqual(version.revision_str(), "r123M (abcd)")
            self.assertEqual(version.caps_to_revision(version.typedict({"revision": 123, "local_modifications": 2,
                                                                       "branch": "master", "commit": "abcd"})), "r123M (abcd)")
            self.assertIn("beta (light build)", version.full_version_str())
            info = version.get_build_info(2)
            self.assertEqual(info["python"], (3, 14, 8))
            self.assertEqual(info["lib"], {"test": (1, 2)})
            self.assertEqual(version.get_build_info(0), {"date": "2026-10-21"})
            os.environ["XPRA_CURRENT_VERSION_BRANCH"] = "v8.0.x"
            self.assertEqual(version.get_branch(), "v8.0.x")
        with patch.dict(sys.modules, {"xpra.src_info": None}), patch.dict(os.environ, {"XPRA_CURRENT_VERSION_BRANCH": ""}):
            self.assertEqual(version.revision_str(), "")
            self.assertEqual(version.get_branch(), "")
        self.assertEqual(version.make_revision_str(12, 0, "v8.0.x", "abcd"), "r12")

    def test_platform_info_is_cached(self):
        info = {"machine": "test"}
        with patch.object(version, "platform_info_cache", None), patch.object(version, "do_get_platform_info", return_value=info) as collect:
            self.assertIs(version.get_platform_info(), info)
            self.assertIs(version.get_platform_info(), info)
            collect.assert_called_once_with()

    def test_host_info_privacy_and_hostname_failure(self):
        self.assertEqual(version.get_host_info(0), {})
        with patch("socket.gethostname", side_effect=OSError("unavailable")):
            info = version.get_host_info(2)
        self.assertNotIn("hostname", info)
        self.assertIn("python", info)

    def test_nested_version_trimming_and_compatibility_errors(self):
        with patch("xpra.net.common.FULL_INFO", 1):
            self.assertEqual(version.dict_version_trim({"nested": {"version": (8, 0, 1)}, "name": "test"}),
                             {"nested": {"version": (8, 0)}, "name": "test"})
        with patch.object(version, "CHECK_PROTOCOL_VERSION", False):
            self.assertEqual(version.protocol_compat_check("invalid"), "")
        self.assertIsNotNone(version.version_compat_check(""))
        self.assertIsNotNone(version.version_compat_check(("bad",)))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
