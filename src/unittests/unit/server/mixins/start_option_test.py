#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import OSX, POSIX, PYTHON2
from unit.server.mixins.server_mixins_option_test_util import ServerMixinsOptionTestUtil


class StartOptionTest(ServerMixinsOptionTestUtil):

    def test_nooptions(self):
        self._test()

    def test_nonotifications(self):
        self._test(options={"notifications" : False})

    def test_start_all(self):
        self._test_all("start")


def main():
    if POSIX and PYTHON2 and not OSX:
        unittest.main()


if __name__ == '__main__':
    main()
