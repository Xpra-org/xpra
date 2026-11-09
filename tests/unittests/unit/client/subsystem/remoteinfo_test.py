#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import typedict, AdHocStruct
from xpra.client.base.remoteinfo import RemoteInfo
from unit.client.subsystem.clientmixintest_util import ClientMixinTest


class RemoteInfoClientTest(ClientMixinTest):

    def test_audio(self):
        waq = []

        def warn_and_quit(*args):
            waq.append(args)
        # the subsystem calls `self.client.warn_and_quit`,
        # and this test harness stands in for the owning client:
        self.warn_and_quit = warn_and_quit
        opts = AdHocStruct()
        caps = typedict({
            "machine_id" : "123",
            "uuid"    : "some-uuid",
            "build.version"    : "3.0",
            "build.revision" : "23000",
            "hostname"    : "localhost",
            "display" : ":99",
            "platform" : "linux2",
            "platform.release" : "dunno",
            "platform.platform" : "platformX",
            "platform.linux_distribution" : ('Linux Fedora', 20, 'Heisenbug'),
        })
        x = self._test_mixin_class(RemoteInfo, opts, caps)
        # servers that don't expose a `protocol-version` are treated as `DEFAULT_PROTOCOL_VERSION`:
        assert x.parse_server_capabilities(caps), "should have accepted a missing protocol version"
        # ie: v7 servers expose 5.1 or 6.6:
        for protocol_version in ((5, 1), (6, 6), (8, 0)):
            caps["protocol-version"] = protocol_version
            assert x.parse_server_capabilities(caps), "should have accepted protocol version %s" % (protocol_version, )
        assert not waq
        # the server requires a newer client:
        caps["protocol-version"] = (99, 0)
        assert not x.parse_server_capabilities(caps), "should have failed with protocol version 99.0"
        assert len(waq) == 1


def main():
    unittest.main()


if __name__ == '__main__':
    main()
