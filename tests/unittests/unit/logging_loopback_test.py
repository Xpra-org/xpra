#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `LoggingClient` subsystem to the
server `LoggingManager` subsystem.

Remote logging (client -> server): the client forwards a log record, the server
decodes the logging-event packet and feeds it to its log sink. Logging has no
per-client source object, so the harness uses the default StubClientConnection.
"""

import logging
import unittest

from xpra.log import Logger
from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import LOGGING_EVENT

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.remote_logging = "send"
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.remote_logging = "receive"
    return opts


class LoggingLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.logging import LoggingClient
        from xpra.server.subsystem.logging import LoggingManager
        from xpra.server.source.stub import StubClientConnection
        # logging has no dedicated source; use the generic one so that
        # get_server_source(proto) returns a connection object:
        return self.connect(LoggingClient, LoggingManager, StubClientConnection,
                            client_opts=_client_opts(), server_opts=_server_opts(),
                            caps={})

    def test_client_log_forwarded_to_server(self):
        client, server, _source = self._connect()
        # capture what the server logs at the end of the pipeline:
        logged = []
        server.do_log = lambda level, line: logged.append((level, line))

        client.remote_logging_handler(Logger("test"), logging.INFO, "hello from client")

        # a logging-event packet crossed the wire:
        self.assertTrue(any(p[0] == LOGGING_EVENT for p in self.c2s),
                        "no logging packet was sent: %s" % (self.c2s,))
        # and the server decoded it and fed it to its log sink:
        self.assertTrue(any("hello from client" in line for _lvl, line in logged),
                        "server did not log the forwarded message: %s" % (logged,))


def main():
    unittest.main()


if __name__ == "__main__":
    main()
