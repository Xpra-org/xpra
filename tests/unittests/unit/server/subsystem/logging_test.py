#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from time import monotonic

from xpra.net.common import Packet
from xpra.util.objects import AdHocStruct
from xpra.server.source.stub import StubClientConnection
from xpra.server.subsystem import logging
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class nostr():
    def __str__(self):
        raise Exception("test format failure")


class InputMixinTest(ServerMixinTest):

    def test_logging(self) -> None:
        opts = AdHocStruct()
        opts.remote_logging = "yes"
        log_messages = []

        def FakeSource():
            s = StubClientConnection()
            s.counter = 0
            return s

        def do_log(level, line):
            log_messages.append((level, line))

        def _LoggingServer():
            ls = logging.LoggingServer()
            ls.do_log = do_log
            return ls

        self._test_mixin_class(_LoggingServer, opts, {}, FakeSource)
        self.handle_packet(Packet("logging", 10, "hello", int(monotonic())))
        message = log_messages[0]
        assert message[0] == 10
        assert message[1].endswith("hello")
        # multi-part:
        self.handle_packet(Packet("logging", 20, ["multi", "messages"], int(monotonic())))
        # invalid:
        try:
            self.handle_packet(Packet("logging", 20, nostr(), int(monotonic())))
        except TypeError:
            pass
        else:
            raise Exception("invalid type was allowed: %s" % (nostr, ))

    def test_invalid(self) -> None:
        l = logging.LoggingServer()
        opts = AdHocStruct()
        opts.remote_logging = "on"
        l.init(opts)
        l._process_logging(None, ())  # pylint: disable=protected-access


def main():
    unittest.main()


if __name__ == '__main__':
    main()
