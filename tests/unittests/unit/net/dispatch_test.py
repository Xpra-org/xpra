#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock

from xpra.net.common import Packet
from xpra.net import dispatch
from xpra.net.dispatch import PacketDispatcher
from unit.test_util import silence_error


class Dispatcher(PacketDispatcher):
    def __init__(self):
        super().__init__()
        self.calls = []

    def call_packet_handler(self, main, handler, proto, packet):
        self.calls.append((main, packet.get_type()))
        handler(proto, packet)


class DispatchTest(unittest.TestCase):

    def test_handler_registration_and_removal(self):
        dispatcher = Dispatcher()
        handler = Mock()
        dispatcher.add_packet_handler("one", handler)
        dispatcher.add_packet_handler("two", handler, main_thread=True)
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": ["one"], "ui": ["two"]})
        dispatcher.remove_packet_handlers("one", "two")
        self.assertEqual(dispatcher.get_info()["packet-handlers"], {"authenticated": [], "ui": []})

    def test_dispatch_routes_and_alias(self):
        dispatcher = Dispatcher()
        handlers = {name: Mock() for name in ("auth", "ui", "default", "default-ui")}
        dispatcher.add_packet_handler("auth", handlers["auth"])
        dispatcher.add_packet_handler("ui", handlers["ui"], main_thread=True)
        dispatcher._default_packet_handlers["default"] = handlers["default"]
        dispatcher._default_ui_packet_handlers["default-ui"] = handlers["default-ui"]
        dispatcher.packet_alias["old"] = "auth"
        proto = Mock()
        proto.is_closed.return_value = False
        for name, authenticated, main in (
                ("old", True, False),
                ("ui", True, True),
                ("default", False, False),
                ("default-ui", False, True),
        ):
            dispatcher.dispatch_packet(proto, Packet(name, 1), authenticated)
            self.assertEqual(dispatcher.calls[-1], (main, "auth" if name == "old" else name))
        for handler in handlers.values():
            handler.assert_called_once()

    def test_invalid_closed_and_handler_error(self):
        dispatcher = Dispatcher()
        proto = Mock()
        proto.is_closed.return_value = False
        dispatcher.dispatch_packet(proto, Packet("missing"))
        proto.close.assert_called_once()
        proto.reset_mock()
        proto.is_closed.return_value = True
        dispatcher.dispatch_packet(proto, Packet("missing"))
        proto.close.assert_not_called()
        handler = Mock(side_effect=ValueError("bad"))
        dispatcher.add_packet_handler("bad", handler)
        proto.is_closed.return_value = False
        with silence_error(dispatch):
            dispatcher.dispatch_packet(proto, Packet("bad"), authenticated=True)
        handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
