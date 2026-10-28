#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from xpra.client.subsystem.socket import NetworkListener


class FakeClient:
    """ minimal stand-in for the owning client (see `StubClientSubsystem.get_subsystem`) """

    def __init__(self):
        self.exit_code = None
        self.subsystems: dict[str, object] = {}

    @staticmethod
    def idle_add(fn, *args) -> int:
        fn(*args)
        return 0

    timeout_add = idle_add

    @staticmethod
    def source_remove(_tid: int) -> None:
        """ nothing to remove: `idle_add` above runs synchronously """


class TestNetworkListener(unittest.TestCase):

    def test_run_twice_listens_once(self):
        # starting a named-pipe listener twice fails with "threads can only be started once":
        listener = NetworkListener(FakeClient())
        listener.sockets = [SimpleNamespace(socktype="named-pipe", socket=None, address="\\\\.\\pipe\\Xpra\\1")]
        with patch("xpra.client.subsystem.socket.start_thread", side_effect=lambda fn, *a, **kw: fn()), \
                patch("xpra.client.subsystem.socket.sleep"), \
                patch("xpra.client.subsystem.socket.add_listen_socket") as add_listen_socket:
            listener.run()
            listener.run()
        add_listen_socket.assert_called_once()


def main():
    unittest.main()


if __name__ == '__main__':
    main()
