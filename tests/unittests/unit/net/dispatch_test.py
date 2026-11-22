#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.client.base import client_base
from xpra.server import server_base


class DispatchTest(unittest.TestCase):

    def test_client_packet_errors_are_contained(self):
        self.check_dispatch(client_base, client_base.XpraClientBase.process_packet,
                            "_packet_handlers", "_ui_packet_handlers")

    def test_server_packet_errors_are_contained(self):
        self.check_dispatch(server_base, server_base.ServerBase.process_packet,
                            "_authenticated_packet_handlers", "_authenticated_ui_packet_handlers")

    def check_dispatch(self, module, process_packet, network_handlers, ui_handlers):
        proto = Mock()
        proto.is_closed.return_value = False
        packet = ("test",)
        for main_thread in (False, True):
            for error in (IndexError, OverflowError):
                with self.subTest(main_thread=main_thread, error=error):
                    handler = Mock(side_effect=error)
                    endpoint = SimpleNamespace(idle_add=Mock(), _server_sources={proto: object()})
                    setattr(endpoint, network_handlers, {} if main_thread else {"test": handler})
                    setattr(endpoint, ui_handlers, {"test": handler} if main_thread else {})
                    with patch.object(module, "netlog") as netlog:
                        process_packet(endpoint, proto, packet)
                        if main_thread:
                            handler.assert_not_called()
                            endpoint.idle_add.assert_called_once()
                            callback, = endpoint.idle_add.call_args.args
                            self.assertIsNone(callback())
                        handler.assert_called_once()
                        netlog.error.assert_called()
                    proto.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
