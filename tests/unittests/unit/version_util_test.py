#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX
from xpra.net.common import FULL_INFO
from xpra.util.version import (
    version_compat_check, protocol_compat_check,
    get_host_info, get_version_info, get_platform_info,
)


class TestVersionUtilModule(unittest.TestCase):

    def test_version_compat_check_invalid(self):
        from xpra import __version__
        self.assertIsNone(version_compat_check(__version__))
        self.assertIsNotNone(version_compat_check("0.1"))

    def test_protocol_compat_check(self):
        from xpra import __version_info__
        from xpra.net.common import BACKWARDS_COMPATIBLE, MIN_PROTOCOL_VERSION
        # we are always compatible with ourselves:
        self.assertFalse(protocol_compat_check(__version_info__))
        # we must satisfy the minimum version we expose to our peers:
        self.assertFalse(protocol_compat_check(MIN_PROTOCOL_VERSION))
        # a missing `protocol-version` is only acceptable in backwards compatible mode:
        for missing in ("", ()):
            self.assertEqual(not BACKWARDS_COMPATIBLE, bool(protocol_compat_check(missing)))
        # we must honour the minimum version required by the remote end,
        # which is never truncated:
        newer = __version_info__[:-1] + (__version_info__[-1] + 1, )
        self.assertTrue(protocol_compat_check(newer))
        self.assertTrue(protocol_compat_check(tuple(__version_info__) + (1, )))
        # invalid versions are rejected rather than causing errors:
        self.assertTrue(protocol_compat_check("%i.%ibeta" % __version_info__[:2]))

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


def main():
    unittest.main()


if __name__ == '__main__':
    main()
