#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.server.base import ServerBase


class TestServerBase(unittest.TestCase):

    def test_handle_invalid_packet_from_detached_protocol(self):
        server = SimpleNamespace(
            _closing=False,
            _potential_protocols=[],
            get_server_source=Mock(return_value=None),
        )
        proto = Mock()
        proto.is_closed.return_value = False
        packet = Packet("logging-event")

        with patch("xpra.server.base.netlog") as netlog:
            ServerBase.handle_invalid_packet(server, proto, packet)

        netlog.assert_called_once_with(
            "packet from detached protocol %s: %s", proto, packet,
        )
        netlog.error.assert_not_called()
        proto.close.assert_called_once_with()

    def test_ui_driver_handover(self) -> None:
        # Cleanup runs in the network thread, so defer the UI driver handover.
        proto1, proto2 = object(), object()
        source1 = SimpleNamespace(uuid="one", counter=1, close=Mock())
        source2 = SimpleNamespace(uuid="two", counter=2, close=Mock())
        server = SimpleNamespace(
            _server_sources={proto1: source1, proto2: source2},
            ui_driver=None,
            server_event=Mock(),
            emit=Mock(),
        )
        server.set_ui_driver = ServerBase.set_ui_driver.__get__(server)
        server.replace_ui_driver = lambda uuid: ServerBase.replace_ui_driver(server, uuid)
        server.set_ui_driver(source1)
        server.emit.reset_mock()

        server._server_sources.pop(proto1)
        with patch("xpra.server.base.GLib.idle_add") as idle_add:
            ServerBase.cleanup_source(server, source1)
        server.emit.assert_called_once_with("client-exited", source1)
        source1.close.assert_called_once_with()
        idle_add.assert_called_once_with(server.replace_ui_driver, "one")
        callback, uuid = idle_add.call_args.args
        callback(uuid)
        self.assertEqual(server.ui_driver, "two")
        server.emit.assert_called_with("new-ui-driver", source2)

        # Another client took over before the handover ran.
        server.set_ui_driver(source1)
        server._server_sources[proto1] = source1
        server.set_ui_driver(source2)
        server.emit.reset_mock()
        server.replace_ui_driver("one")
        self.assertEqual(server.ui_driver, "two")
        server.emit.assert_not_called()
        # The same client reconnected before the handover ran.
        server.set_ui_driver(source1)
        server.emit.reset_mock()
        server.replace_ui_driver("one")
        self.assertEqual(server.ui_driver, "one")
        server.emit.assert_not_called()


def main():
    unittest.main()


if __name__ == "__main__":
    main()
