#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import current_thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xpra.server import server_base
from xpra.server.server_base import ServerBase


class TestServerBase(unittest.TestCase):

    def setUp(self):
        self.driver_handler = Mock()
        for patcher in (
            patch.object(server_base, "SSH_AGENT_DISPATCH", False),
            patch.object(server_base, "SERVER_BASES", (
                server_base.ServerCore, SimpleNamespace(set_session_driver=self.driver_handler),
            )),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def make_server():
        source1 = SimpleNamespace(uuid="one", counter=1, close=Mock())
        source2 = SimpleNamespace(uuid="two", counter=2, close=Mock())
        server = SimpleNamespace(
            _server_sources={object(): source2},
            ui_driver="one",
            server_event=Mock(),
            idle_add=Mock(),
            last_client_exited=Mock(),
        )
        server.set_ui_driver = ServerBase.set_ui_driver.__get__(server)
        server.replace_ui_driver = lambda uuid: ServerBase.replace_ui_driver(server, uuid)
        return server, source1, source2

    def test_ui_driver_handover(self):
        server, source1, source2 = self.make_server()
        handler_threads = []
        self.driver_handler.side_effect = lambda *_args: handler_threads.append(current_thread())
        # Cleanup runs in the network thread; display handlers must wait for the UI loop.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="parse") as executor:
            executor.submit(ServerBase.cleanup_source, server, source1).result(timeout=5)
        self.driver_handler.assert_not_called()
        source1.close.assert_called_once_with()
        server.idle_add.assert_called_once_with(server.replace_ui_driver, "one")
        callback, uuid = server.idle_add.call_args[0]
        callback(uuid)
        self.assertEqual(server.ui_driver, "two")
        self.driver_handler.assert_called_once_with(server, source2)
        self.assertEqual(handler_threads, [current_thread()])

        # Another client took over before the handover ran.
        server.ui_driver = "two"
        self.driver_handler.reset_mock()
        server.replace_ui_driver("one")
        self.assertEqual(server.ui_driver, "two")
        self.driver_handler.assert_not_called()
        # The same client reconnected before the handover ran.
        server.ui_driver = "one"
        server._server_sources[object()] = source1
        server.replace_ui_driver("one")
        self.assertEqual(server.ui_driver, "one")
        self.driver_handler.assert_not_called()

    def test_handover_without_a_single_remaining_client(self):
        for count in (0, 2):
            with self.subTest(remaining=count):
                server, source1, _source2 = self.make_server()
                server._server_sources = {
                    object(): SimpleNamespace(uuid=f"other-{i}") for i in range(count)
                }
                ServerBase.cleanup_source(server, source1)
                self.assertEqual(server.ui_driver, "one")
                self.driver_handler.reset_mock()
                callback, uuid = server.idle_add.call_args_list[0][0]
                callback(uuid)
                self.assertIsNone(server.ui_driver)
                self.driver_handler.assert_called_once_with(server, None)


if __name__ == "__main__":
    unittest.main()
