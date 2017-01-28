#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2011-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.version_util import version_compat_check, get_host_info, get_version_info, get_platform_info


class TestVersionUtilModule(unittest.TestCase):

    def test_version_compat_check_invalid(self):
        from xpra import __version__
        self.assertIsNone(version_compat_check(__version__))
        self.assertIsNotNone(version_compat_check("0.1"))

    def test_get_host_info(self):
        attrs = ["pid"]
        if os.name=="posix":
            attrs += ["uid", "pid"]
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
