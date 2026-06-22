#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

"""
Cross-side interaction test: wires the client `CommandClient` subsystem to the
server `ChildCommandServer` subsystem.

Start-command (client -> server): the client requests a new command, the server
decodes the request and dispatches it to `start_command`. The real
`start_command` spawns a subprocess, so it is replaced with a mock - the test
only checks the request/dispatch contract. There is no dedicated command source,
so the harness uses the generic StubClientConnection.
"""

import unittest
from unittest.mock import patch, MagicMock

from xpra.util.objects import AdHocStruct
from xpra.net.packet_type import COMMAND_START
from xpra.server.source.stub import StubClientConnection

from unit.loopback_util import LoopbackTest


def _client_opts():
    opts = AdHocStruct()
    opts.start_new_commands = "no"
    opts.start = ()
    opts.start_child = ()
    return opts


def _server_opts():
    opts = AdHocStruct()
    opts.start_new_commands = True
    opts.exit_with_children = False
    opts.terminate_children = False
    opts.exec_wrapper = ""
    opts.source_start = ()
    opts.start_env = ()
    for name in (
        "start", "start_late", "start_child", "start_child_late",
        "start_after_connect", "start_child_after_connect",
        "start_on_connect", "start_child_on_connect",
        "start_on_disconnect", "start_child_on_disconnect",
        "start_on_last_client_exit", "start_child_on_last_client_exit",
    ):
        setattr(opts, name, ())
    return opts


class CommandLoopbackTest(LoopbackTest):

    def _connect(self):
        from xpra.client.subsystem.command import CommandClient
        from xpra.server.subsystem.command import ChildCommandServer
        # setup() wires control commands / connect callbacks we don't need here:
        with patch.object(ChildCommandServer, "setup", lambda self: None):
            return self.connect(CommandClient, ChildCommandServer, StubClientConnection,
                                client_opts=_client_opts(), server_opts=_server_opts(), caps={})

    def test_start_command_reaches_server(self):
        client, server, _source = self._connect()
        # the real start_command spawns a subprocess:
        server.start_command = MagicMock()

        client.send_start_command("xterm", ["xterm"], False)

        # the request crossed the wire:
        self.assertTrue(any(p[0] == COMMAND_START for p in self.c2s),
                        "no start-command packet was sent: %s" % (self.c2s,))
        # and the server decoded it and dispatched to start_command:
        server.start_command.assert_called_once()
        args, kwargs = server.start_command.call_args
        self.assertEqual(args[0], "xterm")
        self.assertEqual(args[1], ("xterm",))
        self.assertEqual(kwargs.get("ignore"), False)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
