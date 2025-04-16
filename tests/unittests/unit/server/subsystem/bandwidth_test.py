#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.util.objects import typedict, AdHocStruct
from xpra.util.env import OSEnvContext
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class BandwidthTest(ServerMixinTest):

    def test_bandwidth(self):
        with OSEnvContext():
            os.environ["XPRA_PING_TIMEOUT"] = "1"
            from xpra.server.subsystem.bandwidth import BandwidthServer
            from xpra.server.source import bandwidth
            assert bandwidth.BandwidthConnection.is_needed(typedict({"network-state": True}))
            opts = AdHocStruct()
            opts.bandwidth_limit = "1Gbps"
            opts.bandwidth_detection = False
            # the limit for all clients:
            capped_at = 1*1000*1000*1000    #=="1Gbps"
            with silence_info(bandwidth):
                self._test_mixin_class(BandwidthServer, opts, {}, bandwidth.BandwidthConnection)
            self.assertEqual(capped_at, self.mixin.get_info().get("bandwidth-limit"))
            for v in (None, "foo", 1, 2.0, [], (), set()):
                try:
                    self.handle_packet(("connection-data", v))
                except TypeError:
                    pass
                else:
                    raise Exception("should not allow %s (%s) as connection-data" % (v, type(v)))
            self.handle_packet(("connection-data", {}))
            for v in (None, "foo", 2.0, [], (), set()):
                try:
                    self.handle_packet(("bandwidth-limit", v))
                except TypeError:
                    pass
                else:
                    raise Exception("should not allow %s (%s) as connection-data" % (v, type(v)))
            with silence_info(bandwidth):
                self.handle_packet(("bandwidth-limit", 10*1024*1024))

            def get_limit():
                return self.source.get_info().get("bandwidth-limit", {}).get("setting", 0)
            self.assertEqual(10*1024*1024, get_limit())
            with silence_info(bandwidth):
                self.handle_packet(("bandwidth-limit", bandwidth.MAX_BANDWIDTH_LIMIT+1))
            self.assertEqual(min(capped_at, bandwidth.MAX_BANDWIDTH_LIMIT), get_limit())


def main():
    unittest.main()


if __name__ == '__main__':
    main()
