#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class InputMixinTest(ServerMixinTest):

    def test_input(self):
        with DisplayContext():
            from xpra.server.mixins.input_server import InputServer
            from xpra.server.source.input_mixin import InputMixin
            opts = AdHocStruct()
            self._test_mixin_class(InputServer, opts, {}, InputMixin)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
