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
        del caps["build.version"]
        assert not x.parse_server_capabilities(caps), "should have failed when version is missing"
        version = "0.1"
        caps["build.version"] = version
        assert not x.parse_server_capabilities(caps), "should have failed with version %s" % version


def main():
    unittest.main()


if __name__ == '__main__':
    main()
