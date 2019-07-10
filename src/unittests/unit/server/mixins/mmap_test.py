#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class MMAPMixinTest(ServerMixinTest):

    def test_mmap(self):
        from xpra.server.mixins.mmap_server import MMAP_Server
        opts = AdHocStruct()
        opts.mmap = "on"
        self._test_mixin_class(MMAP_Server, opts)
        assert self.mixin.get_info().get("mmap", {}).get("supported") is True

def main():
    unittest.main()


if __name__ == '__main__':
    main()
