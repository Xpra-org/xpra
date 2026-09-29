#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec

try:
    from xpra.server.dbus.server import DBUS_Server
except ImportError:
    DBUS_Server = None


def get_subsystem_classes() -> dict[str, type]:
    # the real subsystem classes, so that calling a method they don't have fails:
    from xpra.server.subsystem.window import WindowServer
    from xpra.server.subsystem.keyboard import KeyboardManager
    from xpra.server.subsystem.pointer import PointerManager
    from xpra.server.subsystem.command import ChildCommandServer
    from xpra.server.subsystem.sharing import SharingServer
    from xpra.server.subsystem.notification import NotificationForwarder
    from xpra.server.subsystem.info import InfoServer
    from xpra.server.subsystem.display import DisplayManager
    classes = {
        "display": DisplayManager,
        "window": WindowServer,
        "keyboard": KeyboardManager,
        "pointer": PointerManager,
        "command": ChildCommandServer,
        "sharing": SharingServer,
        "notification": NotificationForwarder,
        "info": InfoServer,
    }
    try:
        from xpra.x11.subsystem.xsettings import XSettingsServer
        classes["xsettings"] = XSettingsServer
    except ImportError:
        pass
    return classes


@unittest.skipUnless(DBUS_Server, "dbus bindings are not available")
class DBUSServerMethodsTest(unittest.TestCase):
    """
        The dbus methods must reach the subsystem which implements them,
        see the subsystem refactoring which moved these methods out of the server class.
    """

    def setUp(self) -> None:
        from xpra.server.base import ServerBase
        self.subsystems = {
            name: create_autospec(cls, instance=True)
            for name, cls in get_subsystem_classes().items()
        }
        window = self.subsystems["window"]
        window._id_to_window = {
            1: MagicMock(**{"get_property.return_value": "title1"}),
            2: MagicMock(**{"get_property.return_value": "title2"}),
        }
        self.source = SimpleNamespace(uuid="source-uuid", protocol="protocol")
        self.server = create_autospec(ServerBase, instance=True)
        self.server.get_subsystem.side_effect = self.subsystems.get
        self.server.get_sources_by_type.return_value = [self.source]
        # we call the methods unbound, with a minimal stand-in for the dbus object:
        self.dbus_server = SimpleNamespace(server=self.server, log=lambda *_args: None)

    def call(self, method: str, *args):
        return getattr(DBUS_Server, method)(self.dbus_server, *args)

    def test_window_control(self) -> None:
        window = self.subsystems["window"]
        self.call("Focus", 1)
        window.control_command_focus.assert_called_once_with(1)
        self.call("Suspend")
        window.control_command_suspend.assert_called_once_with()
        self.call("Resume")
        window.control_command_resume.assert_called_once_with()
        self.call("Ungrab")
        window.control_command_ungrab.assert_called_once_with()

    def test_video_region(self) -> None:
        window = self.subsystems["window"]
        self.call("SetVideoRegion", 1, 0, 0, 10, 20)
        window.control_command_video_region.assert_called_once_with(1, 0, 0, 10, 20)
        self.call("SetVideoRegionEnabled", 1, True)
        window.control_command_video_region_enabled.assert_called_once_with(1, True)
        self.call("SetVideoRegionDetection", 1, False)
        window.control_command_video_region_detection.assert_called_once_with(1, False)
        self.call("SetVideoRegionExclusionZones", 1, [[0, 0, 1, 1]])
        window.control_command_video_region_exclusion_zones.assert_called_once()
        self.call("ResetVideoRegion", 1)
        window.control_command_reset_video_region.assert_called_once_with(1)
        self.call("LockBatchDelay", 1, 50)
        window.control_command_lock_batch_delay.assert_called_once_with(1, 50)
        self.call("UnlockBatchDelay", 1)
        window.control_command_unlock_batch_delay.assert_called_once_with(1)

    def test_window_settings(self) -> None:
        window = self.subsystems["window"]
        self.call("MoveWindowToWorkspace", 1, 2)
        window.control_command_workspace.assert_called_once_with(1, 2)
        self.call("SetWindowScaling", 1, "2")
        window.control_command_scaling.assert_called_once()
        self.call("SetWindowScalingControl", 1, "50")
        window.control_command_scaling_control.assert_called_once()
        self.call("SetWindowEncoding", 1, "png")
        window.control_command_encoding.assert_called_once_with("png", 1)
        self.call("ResetWindowFilters")
        window.reset_window_filters.assert_called_once_with()

    def test_refresh(self) -> None:
        window = self.subsystems["window"]
        self.call("RefreshWindow", 1)
        window.control_command_refresh.assert_called_with(1)
        self.call("RefreshWindows", [1, 2])
        window.control_command_refresh.assert_called_with(1, 2)
        self.call("RefreshAllWindows")
        window.control_command_refresh.assert_called_with(1, 2)

    def test_list_windows(self) -> None:
        self.assertEqual(dict(self.call("ListWindows")), {1: "title1", 2: "title2"})

    def test_start(self) -> None:
        command = self.subsystems["command"]
        self.call("Start", "xterm -e 'echo hello'")
        # the command line must be split, like the control channel does:
        command.do_control_command_start.assert_called_once_with(True, "xterm", "-e", "echo hello")
        command.do_control_command_start.reset_mock()
        self.call("StartChild", "true")
        command.do_control_command_start.assert_called_once_with(False, "true")

    def test_keyboard(self) -> None:
        keyboard = self.subsystems["keyboard"]
        self.call("KeyPress", 38)
        keyboard.control_command_key.assert_called_with("38", press=True)
        self.call("KeyRelease", 38)
        keyboard.control_command_key.assert_called_with("38", press=False)
        self.call("ClearKeysPressed")
        keyboard.clear_keys_pressed.assert_called_once_with()

    def test_mouse_click(self) -> None:
        self.call("MouseClick", 1, True)
        self.subsystems["pointer"].button_action.assert_called_once()

    def test_sharing(self) -> None:
        sharing = self.subsystems["sharing"]
        self.call("SetLock", "yes")
        sharing.control_command_set_lock.assert_called_once_with("yes")
        self.call("SetSharing", "no")
        sharing.control_command_set_sharing.assert_called_once_with("no")

    def test_ui_driver(self) -> None:
        self.call("SetUIDriver", "source-uuid")
        self.server.set_ui_driver.assert_called_once_with(self.source)
        self.server.set_ui_driver.reset_mock()
        self.call("SetUIDriver", "unknown-uuid")
        self.server.set_ui_driver.assert_not_called()

    def test_notifications(self) -> None:
        notification = self.subsystems["notification"]
        self.call("SendNotification", 1, "title", "message", "*")
        notification.control_command_send_notification.assert_called_once_with(1, "title", "message", "*")
        self.call("CloseNotification", 1, "*")
        notification.control_command_close_notification.assert_called_once_with(1, "*")

    def test_info(self) -> None:
        info = self.subsystems["info"]
        errors = []
        self.call("GetAllInfo", None, errors.append)
        info.get_all_info.assert_called_once()
        self.call("GetInfo", "window", None, errors.append)
        self.assertEqual(info.get_all_info.call_args.kwargs, {"subsystems": ("window", )})
        self.assertEqual(errors, [])

    def test_info_missing(self) -> None:
        del self.subsystems["info"]
        errors = []
        self.call("GetAllInfo", None, errors.append)
        self.call("GetInfo", "window", None, errors.append)
        self.assertEqual(len(errors), 2)

    def test_missing_subsystems(self) -> None:
        # none of the methods should fail when the subsystem is not available:
        self.subsystems.clear()
        for method, args in {
            "Focus": (1, ),
            "Suspend": (),
            "Ungrab": (),
            "Start": ("true", ),
            "KeyPress": (38, ),
            "MouseClick": (1, True),
            "SetVideoRegion": (1, 0, 0, 10, 10),
            "SetLock": ("yes", ),
            "RefreshAllWindows": (),
            "SendNotification": (1, "title", "message", "*"),
        }.items():
            self.call(method, *args)
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        X11_DBUS_Server.SetDPI(self.dbus_server, 120, 144)
        self.assertEqual(dict(self.call("ListWindows")), {})

    def test_set_dpi(self) -> None:
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        X11_DBUS_Server.SetDPI(self.dbus_server, 120, 144)
        self.subsystems["display"].update_dpi.assert_called_once_with(120, 144)
        with self.assertRaises(ValueError):
            X11_DBUS_Server.SetDPI(self.dbus_server, 0, 144)
        self.subsystems["display"].update_dpi.assert_called_once()

    def test_reset_xsettings(self) -> None:
        if "xsettings" not in self.subsystems:
            raise unittest.SkipTest("xsettings subsystem is not available")
        from xpra.x11.dbus.x11_dbus_server import X11_DBUS_Server
        X11_DBUS_Server.ResetXSettings(self.dbus_server)
        self.subsystems["xsettings"].update_all_server_settings.assert_called_once_with(True)


def main():
    unittest.main()


if __name__ == "__main__":
    main()
