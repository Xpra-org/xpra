#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.os_util import getuid, getgid
from xpra.util.objects import typedict, AdHocStruct
from xpra.server.subsystem.stub import StubSubsystem


class EncodingMixinTest(unittest.TestCase):

    def test_mixin_methods(self):
        opts = AdHocStruct()
        opts.uid = getuid()
        opts.gid = getgid()
        x = StubSubsystem()
        x.init(opts)
        x.init_state()
        x.setup()
        x.init_packet_handlers()
        # `get_server_source` is a delegate to `self.server`; calling it on a
        # bare stub (whose `self.server is self`) would recurse - skip here.

        assert isinstance(x.get_caps(None), dict)
        assert isinstance(x.get_server_features(None), dict)
        assert isinstance(x.get_info(None), dict)
        assert isinstance(x.get_ui_info(None), dict)

        caps = typedict()
        x.parse_hello(None, caps)
        x.add_new_client(None, caps)
        x.send_initial_data(caps)

        x.cleanup_protocol(None)
        x.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
