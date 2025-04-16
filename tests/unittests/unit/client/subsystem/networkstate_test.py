#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from xpra.util.objects import AdHocStruct
from xpra.client.base.network import NetworkClient
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class MixinsTest(ClientMixinTest):

    def test_networkclient(self):
        opts = AdHocStruct()
        opts.pings = True
        opts.bandwidth_limit = 0
        opts.bandwidth_detection = True
        self._test_mixin_class(NetworkClient, opts, {"start_time": time.time()})


def main():
    unittest.main()


if __name__ == '__main__':
    main()
