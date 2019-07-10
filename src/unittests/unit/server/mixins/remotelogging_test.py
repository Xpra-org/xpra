#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2018-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct
from unit.server.mixins.servermixintest_util import ServerMixinTest


class ServerMixinsTest(ServerMixinTest):

    def test_remotelogging(self):
        from xpra.server.mixins.logging_server import LoggingServer, log
        logfn = log.log
        try:
            messages = []
            def newlogfn(*args):
                messages.append(args)
            log.log = newlogfn
            proto = AdHocStruct()
            def _LoggingServer():
                ls = LoggingServer()
                ls._server_sources = {proto : "fake-source"}
                return ls
            opts = AdHocStruct()
            opts.remote_logging = "on"
            level = 20
            msg = "foo"
            packet = ["logging", level, msg]
            self._test_mixin_class(_LoggingServer, opts)
            self.mixin._process_logging(proto, packet)
            assert len(messages)==1
        finally:
            log.log = logfn

def main():
    unittest.main()


if __name__ == '__main__':
    main()
