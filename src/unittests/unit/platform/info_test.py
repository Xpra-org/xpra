#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import POSIX
from xpra.platform.info import get_sys_info, get_version_info, get_user_info


class PlatformInfoTest(unittest.TestCase):

    def test_all_info(self):
        if POSIX:
            assert get_sys_info()
        assert isinstance(get_version_info(), dict)
        assert isinstance(get_user_info(), dict)


def main():
    unittest.main()

if __name__ == '__main__':
    main()
