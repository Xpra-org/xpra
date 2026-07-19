#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from xpra.client.subsystem.tray import TrayClient
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class AudioClientTest(ClientMixinTest):

    def test_tray(self):
        # `after_handshake` is called on the owning client (`self.client.after_handshake`),
        # and the test harness provides it as the client stand-in:
        opts = AdHocStruct()
        opts.tray = True
        opts.delay_tray = 0
        opts.tray_icon = ""
        self._test_mixin_class(TrayClient, opts)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
