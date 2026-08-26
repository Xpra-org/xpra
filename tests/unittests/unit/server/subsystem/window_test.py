#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from unittest.mock import Mock, patch

from xpra.net.common import Packet
from xpra.net.packet_type import WINDOW_CREATE
from xpra.util.objects import AdHocStruct, typedict
from unit.test_util import stubbable
from unit.server.subsystem.servermixintest_util import ServerMixinTest


class WebcamMixinTest(ServerMixinTest):

    @staticmethod
    def make_initial_window_server(geometry):
        from xpra.server.subsystem.window import WindowServer

        server = object.__new__(WindowServer)
        window = Mock()
        window.is_managed.return_value = True
        window.is_tray.return_value = False
        window.is_OR.return_value = False
        window.get_property.return_value = geometry
        server._id_to_window = {1: window}
        server.client_properties = {}
        return server, window

    def test_initial_window_waits_for_nonzero_dimensions(self):
        server, window = self.make_initial_window_server((10, 20, 0, 0))
        source = Mock(uuid="client")

        server.send_initial_windows(source)

        window.hide.assert_not_called()
        source.new_window.assert_not_called()
        source.damage.assert_not_called()

        server, window = self.make_initial_window_server((10, 20, 800, 600))
        source = Mock(uuid="client")

        server.send_initial_windows(source)

        source.new_window.assert_called_once_with(
            WINDOW_CREATE, 1, window, 10, 20, 800, 600, {},
        )
        source.damage.assert_called_once_with(1, window, 0, 0, 800, 600)

    def test_window_stacking_packet(self):
        from xpra.server.subsystem.window import WindowServer

        window_server = stubbable(WindowServer)(self)
        window_server.update_window_stacking = Mock()
        origin = Mock()
        recorder = Mock(window_sync_stacking=True)
        regular = Mock(window_sync_stacking=False)
        window_server.get_server_source = Mock(return_value=origin)
        window_server.window_sources = Mock(return_value=(recorder, regular))
        window_server._process_stacking(object(), Packet("window-stacking", [3, 1, 2]))
        window_server.update_window_stacking.assert_called_once_with((3, 1, 2))
        window_server.window_sources.assert_called_once_with(exclude=origin)
        recorder.send_window_stacking.assert_called_once_with((3, 1, 2))
        regular.send_window_stacking.assert_not_called()

    def test_x11_window_stacking_filter(self):
        from xpra.x11.subsystem.window import SeamlessWindowServer

        def window(xid: int, override_redirect=False, tray=False):
            model = Mock()
            model.is_OR.return_value = override_redirect
            model.is_tray.return_value = tray
            model.get_property.return_value = xid
            return model

        manager = SeamlessWindowServer(AdHocStruct())
        manager._wm = Mock()
        manager._id_to_window = {
            1: window(0x101),
            2: window(0x102, override_redirect=True),
            3: window(0x103, tray=True),
            4: window(0x104),
        }
        manager.update_window_stacking((4, 2, 99, 1, 3, 4))
        manager._wm.update_window_stacking.assert_called_once_with([0x104, 0x101])

    def test_x11_window_stacking_capability(self):
        from xpra.server.base import ServerBase
        from xpra.x11.server.seamless import SeamlessServer

        server = SeamlessServer.__new__(SeamlessServer)
        server.subsystems = {"window": object()}
        with patch.object(ServerBase, "get_server_features", return_value={}):
            features = SeamlessServer.get_server_features(server)
        self.assertTrue(typedict(features).boolget("window.stacking"))

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
        self.assertIn("window-stacking", self.mixin.get_packet_types())
        self.assertFalse(typedict(self.mixin.get_server_features(None)).boolget("window.stacking"))

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
