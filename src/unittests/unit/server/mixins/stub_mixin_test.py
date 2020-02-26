#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util import AdHocStruct, typedict
from xpra.make_thread import start_thread
from xpra.server.mixins.stub_server_mixin import StubServerMixin


class EncodingMixinTest(unittest.TestCase):

    def test_mixin_methods(self):
        opts = AdHocStruct()
        x = StubServerMixin()
        x.init(opts)
        x.init_state()
        x.init_sockets([])
        x.setup()
        t = start_thread(x.threaded_setup, "threaded setup")
        t.join()
        x.init_packet_handlers()
        x.add_packet_handler("foo", self.test_mixin_methods, main_thread=True)
        x.add_packet_handler("bar", self.test_mixin_methods, main_thread=False)
        x.add_packet_handlers({
            "hello" : self.test_mixin_methods,
            "world" : self.test_mixin_methods,
            }, main_thread=True)

        x.get_server_source(None)

        assert isinstance(x.get_caps(None), dict)
        assert isinstance(x.get_server_features(None), dict)
        assert isinstance(x.get_info(None), dict)
        assert isinstance(x.get_ui_info(None, None), dict)

        caps = typedict()
        x.parse_hello(None, caps, True)
        x.add_new_client(None, caps, True, 1)
        x.send_initial_data(None, caps, True, 1)

        x.reset_focus()
        x.last_client_exited()
        x.set_session_driver(None)

        x.cleanup_protocol(None)
        x.cleanup()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
