#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import unittest

from xpra.net.common import BACKWARDS_COMPATIBLE
from xpra.util.objects import typedict, AdHocStruct
from xpra.util.env import OSEnvContext
from unit.test_util import silence_info
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class BandwidthTest(ServerMixinTest):

    def test_bandwidth(self):
        with OSEnvContext():
            os.environ["XPRA_PING_TIMEOUT"] = "1"
            from xpra.server.subsystem.bandwidth import BandwidthManager, MAX_BANDWIDTH_LIMIT
            from xpra.server.source import bandwidth
            # `network-state` only triggers the subsystem in backwards-compatible mode:
            if BACKWARDS_COMPATIBLE:
                assert bandwidth.BandwidthConnection.is_needed(typedict({"network-state": True}))
            assert bandwidth.BandwidthConnection.is_needed(typedict({"bandwidth": True}))
            opts = AdHocStruct()
            opts.bandwidth_limit = "1Gbps"
            opts.bandwidth_detection = False
            # the limit for all clients:
            capped_at = 1*1000*1000*1000    # == "1Gbps"
            with silence_info(bandwidth):
                self._test_mixin_class(BandwidthManager, opts, {}, bandwidth.BandwidthConnection)

            def get_info_limit(obj) -> int:
                print("%s.info=%s" % (obj, obj.get_info(),))
                return obj.get_info().get("bandwidth", {}).get("limit", 0)

            self.assertEqual(capped_at, get_info_limit(self.mixin))
            for v in (None, "foo", 1, 2.0, [], (), set()):
                try:
                    self.handle_packet(("bandwidth-status", v))
                except TypeError:
                    pass
                else:
                    raise Exception("should not allow %s (%s) as bandwidth-status" % (v, type(v)))
            self.handle_packet(("bandwidth-status", {}))
            for v in (None, "foo", 2.0, [], (), set()):
                try:
                    self.handle_packet(("bandwidth-limit", v))
                except (TypeError, ValueError):
                    pass
                else:
                    raise Exception("should not allow %s (%s) as connection-data" % (v, type(v)))
            with silence_info(bandwidth):
                self.handle_packet(("bandwidth-limit", 10*1024*1024))

            self.assertEqual(10*1024*1024, get_info_limit(self.source))
            with silence_info(bandwidth):
                self.handle_packet(("bandwidth-limit", MAX_BANDWIDTH_LIMIT+1))
            self.assertEqual(min(capped_at, MAX_BANDWIDTH_LIMIT), get_info_limit(self.source))


def main():
    unittest.main()


if __name__ == '__main__':
    main()
