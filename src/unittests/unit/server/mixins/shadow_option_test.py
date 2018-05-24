#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from unit.server.mixins.server_mixins_option_test_util import ServerMixinsOptionTestUtil


class StartDesktopOptionTest(ServerMixinsOptionTestUtil):

    def test_start_all(self):
        self._test_all("shadow")


def main():
    from xpra.os_util import WIN32
    if not WIN32:
        unittest.main()
    #for running on win32:
    #XPRA_WAIT_FOR_INPUT=0 XPRA_COMMAND=../scripts/xpra \
    #    PYTHONPATH=".;.." XPRA_TEST_DEBUG=1 XPRA_ALL_DEBUG=1 \
    #    ./unit/server/mixins/shadow_option_test.py        


if __name__ == '__main__':
    main()
