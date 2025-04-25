#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util.objects import typedict, AdHocStruct
from xpra.util.env import OSEnvContext
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class PingTest(ServerMixinTest):

    def test_pings(self):
        with OSEnvContext():
            os.environ["XPRA_PING_TIMEOUT"] = "1"
            from xpra.server.subsystem.ping import PingServer
            from xpra.server.source.ping import PingConnection
            assert PingConnection.is_needed(typedict({"network": {"pings": 1}}))
            opts = AdHocStruct()
            opts.pings = 1
            self._test_mixin_class(PingServer, opts, source_mixin_class=PingConnection)
            self.handle_packet(("ping", 10))
            try:
                self.handle_packet(("ping", -1000))
            except ValueError:
                pass
            else:
                raise ValueError("negative values are not allowed for pings")
            self.handle_packet(("ping_echo", 10, 500, 500, 600, 10))

            # test source:
            timeouts = []

            def timeout(*args):
                timeouts.append(args)
            self.source.disconnect = timeout
            assert self.source.get_caps()
            self.source.ping()
            self.source.check_ping_echo_timeout(0, 0)
            # give time for the timeout to fire:
            self.glib.timeout_add(2000, self.main_loop.quit)
            self.main_loop.run()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
