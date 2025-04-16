#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.client.subsystem.clientmixintest_util import ClientMixinTest
from unit.process_test_util import DisplayContext


class KeyboardClientTest(ClientMixinTest):

    def test_keyboard(self):
        from xpra.client.subsystem.keyboard import KeyboardClient
        opts = AdHocStruct()
        self._test_mixin_class(KeyboardClient, opts, {})
        self.glib.timeout_add(5000, self.stop)
        self.main_loop.run()


def main() -> None:
    with DisplayContext():
        unittest.main()


if __name__ == '__main__':
    main()
