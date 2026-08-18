#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.util.objects import AdHocStruct, typedict
from unit.test_util import stubbable
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class WebcamMixinTest(ServerMixinTest):

    def test_monitor_relative_geometry(self):
        from xpra.x11.subsystem.window import SeamlessWindowServer
        source = AdHocStruct()
        source.get_monitor_position = lambda index, position: (100, 1250) if (index, position) == (0, (100, 50)) else None
        server = AdHocStruct()
        server.get_server_source = lambda _proto: source
        geometry = SeamlessWindowServer.resolve_monitor_geometry(
            server, object(), (32000, 50, 800, 600),
            typedict({"index": 0, "position": (100, 50)}),
        )
        self.assertEqual(geometry, (100, 1250, 800, 600))
        fallback = SeamlessWindowServer.resolve_monitor_geometry(
            server, object(), (10, 20, 800, 600),
            typedict({"index": 99, "position": (100, 50)}),
        )
        self.assertEqual(fallback, (10, 20, 800, 600))

    def test_monitor_relative_pointer(self):
        from xpra.x11.server import pointer
        from xpra.server.subsystem.pointer import PointerManager
        from xpra.x11.subsystem.pointer import X11PointerManager

        self.assertEqual(
            PointerManager.get_pointer_window_position(
                (32000, 50), {"window-position": (10, 20)},
            ),
            (10, 20),
        )
        self.assertEqual(
            PointerManager.get_pointer_window_position((32000, 50, 30, 40)),
            (30, 40),
        )
        source = AdHocStruct()
        source.get_monitor_position = lambda index, position: (100, 1250) if (index, position) == (0, (100, 50)) else None
        server = AdHocStruct()
        server.idle_add = lambda *args: None
        server.timeout_add = lambda *args: None
        server.source_remove = lambda *args: None
        server.subsystems = {}
        server.get_server_source = lambda _proto: source
        manager = pointer.X11SeamlessPointerManager(server)
        target = manager.get_pointer_target(
            object(), 1, (32000, 50),
            {"monitor": {"index": 0, "position": (100, 50)}},
        )
        self.assertEqual(target, (100, 1250))
        generic = X11PointerManager(server)
        self.assertEqual(
            generic.get_pointer_target(
                object(), 1, (32000, 50),
                {"monitor": {"index": 0, "position": (100, 50)}},
            ),
            (32000, 50),
        )

    def test_windowserver(self):
        from xpra.server.subsystem.window import WindowServer
        opts = AdHocStruct()
        opts.min_size = "10x10"
        opts.max_size = "16384x8192"

        def load_existing_windows():
            pass

        def _WindowServer(server):
            ws = stubbable(WindowServer)(server)
            ws.load_existing_windows = load_existing_windows
            return ws
        self._test_mixin_class(_WindowServer, opts)

    def test_power_events_cleanup_video_encoders(self):
        from xpra.server.subsystem.window import WindowServer

        window_server = stubbable(WindowServer)(self)
        window_server.update_size_constraints = lambda *_args: None
        window_server.load_existing_windows = lambda: None
        window_server.add_window_control_commands = lambda: None

        source = AdHocStruct()
        source.cleanup_video_encoders = Mock()
        window_server.window_sources = lambda: (source,)
        with patch("xpra.server.subsystem.window.add_handler") as add_handler, \
                patch("xpra.server.subsystem.window.remove_handler") as remove_handler:
            window_server.setup()
            add_handler.assert_any_call("suspend", window_server.suspend_event)
            add_handler.assert_any_call("resume", window_server.resume_event)
            window_server.suspend_event()
            window_server.resume_event()
            self.assertEqual(source.cleanup_video_encoders.call_count, 2)
            window_server.cleanup()
            remove_handler.assert_any_call("suspend", window_server.suspend_event)
            remove_handler.assert_any_call("resume", window_server.resume_event)


def main():
    unittest.main()


if __name__ == '__main__':
    main()
