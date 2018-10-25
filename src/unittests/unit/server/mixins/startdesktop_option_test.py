#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX, POSIX
from unit.server.mixins.server_mixins_option_test_util import ServerMixinsOptionTestUtil


class StartDesktopOptionTest(ServerMixinsOptionTestUtil):

    def test_start_all(self):
        self._test_all("start-desktop")


def main():
    if POSIX and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
