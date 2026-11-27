#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util.objects import typedict, AdHocStruct
from xpra.util.env import OSEnvContext
from xpra.net.packet_type import PING_ECHO
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
            self.handle_packet((PING_ECHO, 10, 500, 500, 600, 10))

            # test source:
            timeouts = []

            def timeout(*args):
                timeouts.append(args)
            self.source.disconnect = timeout
            assert True
            self.source.ping()
            self.source.check_ping_echo_timeout(0, 0)
            # give time for the timeout to fire:
            self.glib.timeout_add(2000, self.main_loop.quit)
            self.main_loop.run()

    def test_ping_dropped_when_source_lacks_mixin(self):
        # a client that sends ping packets without having negotiated the ping
        # subsystem gets a source without `PingConnection`: the handler must drop
        # the packet rather than raising `AttributeError` (see ping-DoS-client.py).
        from xpra.server.subsystem.ping import PingServer
        from xpra.server.source.ping import PingConnection
        opts = AdHocStruct()
        opts.pings = 1
        self._test_mixin_class(PingServer, opts, source_mixin_class=PingConnection)

        class NotPing:
            """ a source assembled without the ping mixin """
        self.source = NotPing()
        # neither of these must raise:
        self.handle_packet(("ping", 10))
        self.handle_packet((PING_ECHO, 10, 500, 500, 600, 10))
        # the dummy source has no `cleanup()`, drop it before teardown:
        self.source = None


def main():
    unittest.main()


if __name__ == '__main__':
    main()
