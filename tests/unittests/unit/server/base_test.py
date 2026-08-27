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


def main():
    unittest.main()


if __name__ == "__main__":
    main()
