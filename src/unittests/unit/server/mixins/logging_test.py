#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class InputMixinTest(ServerMixinTest):

    def test_logging(self):
        from xpra.server.mixins.logging_server import LoggingServer
        opts = AdHocStruct()
        opts.remote_logging = "yes"
        self._test_mixin_class(LoggingServer, opts)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
