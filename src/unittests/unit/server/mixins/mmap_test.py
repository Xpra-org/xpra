#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class ServerMixinsTest(ServerMixinTest):

    def test_mmap(self):
        from xpra.server.mixins.mmap_server import MMAP_Server
        x = MMAP_Server()
        self.mixin = x
        opts = AdHocStruct()
        opts.mmap = "on"
        x.init(opts)
        assert x.get_info().get("mmap", {}).get("supported") is True

def main():
    unittest.main()


if __name__ == '__main__':
    main()
