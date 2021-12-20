#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import time
import unittest

from unit.test_util import silence_error
from xpra.util import AdHocStruct
from xpra.server.source.stub_source_mixin import StubSourceMixin
from xpra.server.mixins import logging_server
from unit.server.mixins.servermixintest_util import ServerMixinTest


class nostr():
    def __str__(self):
        raise Exception("test format failure")

class InputMixinTest(ServerMixinTest):

    def test_logging(self):
        opts = AdHocStruct()
        opts.remote_logging = "yes"
        log_messages = []
        def FakeSource():
            s = StubSourceMixin()
            s.counter = 0
            return s
        def do_log(level, line):
            log_messages.append((level, line))
        def _LoggingServer():
            ls = logging_server.LoggingServer()
            ls.do_log = do_log
            return ls
        self._test_mixin_class(_LoggingServer, opts, {}, FakeSource)
        self.handle_packet(("logging", 10, "hello", time.time()))
        message = log_messages[0]
        assert message[0]==10
        assert message[1].endswith("hello")
        #multi-part:
        self.handle_packet(("logging", 20, ["multi", "messages"], time.time()))
        #invalid:
        with silence_error(logging_server):
            self.handle_packet(("logging", 20, nostr(), time.time()))


    def test_invalid(self):
        l = logging_server.LoggingServer()
        opts = AdHocStruct()
        opts.remote_logging = "on"
        l.init(opts)
        l._process_logging(None, None)  #pylint: disable=protected-access


def main():
    unittest.main()


if __name__ == '__main__':
    main()
