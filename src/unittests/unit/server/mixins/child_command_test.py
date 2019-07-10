#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class ServerMixinsTest(ServerMixinTest):

    def test_mmap(self):
        from xpra.server.mixins.child_command_server import ChildCommandServer
        opts = AdHocStruct()
        opts.exit_with_children = True
        opts.terminate_children = True
        opts.start_new_commands = True
        opts.start = []
        opts.start_child = []
        opts.start_after_connect = []
        opts.start_child_after_connect = []
        opts.start_on_connect = []
        opts.start_child_on_connect = []
        opts.start_on_last_client_exit = []
        opts.start_child_on_last_client_exit = []
        opts.exec_wrapper = None
        opts.start_env = []
        self._test_mixin_class(ChildCommandServer, opts)

def main():
    unittest.main()


if __name__ == '__main__':
    main()
