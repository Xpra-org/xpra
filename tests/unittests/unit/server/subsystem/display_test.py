#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.util.objects import AdHocStruct
from unit.test_util import stubbable
from unit.server.subsystem.servermixintest_util import ServerMixinTest
from unit.process_test_util import DisplayContext


class DisplayMixinTest(ServerMixinTest):

    def test_display(self):
        with DisplayContext():
            self.do_test_display()

    def do_test_display(self):
        from xpra.server.subsystem.display import DisplayManager
        from xpra.server.source.display import DisplayConnection
        opts = AdHocStruct()
        opts.bell = True
        opts.cursors = True
        opts.dpi = 144
        opts.opengl = "no"
        opts.refresh_rate = "auto"
        opts.resize_display = "no"
        opts.sharing = "auto"

        def calculate_workarea(*_args) -> None:
            pass

        def set_desktop_geometry(*_args) -> None:
            pass

        # `set_desktop_geometry` is called on the owning server
        # (`self.server.set_desktop_geometry`), and this test class stands in for it:
        self.set_desktop_geometry = set_desktop_geometry

        def make_display_manager(server):
            dm = stubbable(DisplayManager)(server)
            dm.calculate_workarea = calculate_workarea
            return dm
        # modern clients send their display attributes in the `display` namespace,
        # which `DisplayConnection.parse_client_caps` requires with BC=0
        # (with BC=1 the namespaced form is honoured too):
        caps = {
            "display": {
                "desktop_size": (1024, 768),
                "refresh-rate": 60,
                "resize-events": True,
            },
        }
        self._test_mixin_class(make_display_manager, opts, caps, DisplayConnection)


class ConfigureDisplayTest(unittest.TestCase):

    def test_dpi_change(self):
        # a DPI change must not prevent the rest of the display configuration from being applied
        from unittest.mock import Mock
        from xpra.net.common import Packet
        from xpra.server.subsystem.display import DisplayManager
        opts = AdHocStruct()
        opts.dpi = 96
        opts.refresh_rate = "auto"
        opts.sharing = "auto"
        xsettings = Mock()
        server = AdHocStruct()
        server.hello_request_handlers = {}
        server.subsystems = {"xsettings": xsettings}
        server.calculate_desktops = Mock()
        ss = Mock()
        server.get_server_source = lambda _proto: ss
        dm = stubbable(DisplayManager)(server)
        dm.init(opts)
        dm.apply_refresh_rate = Mock()
        dm._process_configure(None, Packet("configure-display", {
            "dpi": {"x": 120, "y": 144},
            "desktop-names": ("one", "two"),
        }))
        self.assertEqual((dm.xdpi, dm.ydpi, dm.dpi), (120, 144, 132))
        ss.set_desktops.assert_called_once_with(2, ("one", "two"))
        server.calculate_desktops.assert_called_once_with()
        dm.apply_refresh_rate.assert_called_once_with(ss)
        xsettings.update_all_server_settings.assert_called_once_with()

    def test_update_dpi(self):
        # ie: from dbus `SetDPI`, the new value must be used for the xsettings
        from unittest.mock import Mock
        from xpra.server.subsystem.display import DisplayManager
        opts = AdHocStruct()
        opts.dpi = 96
        opts.refresh_rate = "auto"
        opts.sharing = "auto"
        xsettings = Mock()
        server = AdHocStruct()
        server.hello_request_handlers = {}
        server.subsystems = {"xsettings": xsettings}
        dm = stubbable(DisplayManager)(server)
        dm.init(opts)
        dm.apply_dpi = Mock()
        dm.update_dpi(120, 144)
        self.assertEqual((dm.xdpi, dm.ydpi, dm.dpi), (120, 144, 132))
        dm.apply_dpi.assert_called_once_with()
        xsettings.update_all_server_settings.assert_called_once_with()

    def test_x11_apply_dpi(self):
        # the physical dimensions of the display must match the new DPI:
        from unittest.mock import Mock, patch
        try:
            from xpra.x11.subsystem import display
        except ImportError as e:
            raise unittest.SkipTest(f"x11 display subsystem is not available: {e}") from None
        server = AdHocStruct()
        server.hello_request_handlers = {}
        server.subsystems = {}
        server.set_dpi = Mock()
        # without randr, so that we don't need an X11 display:
        dm = stubbable(display.X11DisplayManager)(server)
        self.assertFalse(dm.randr)
        with patch.object(display, "get_root_size", return_value=(1920, 1080)):
            dm.update_dpi(120, 144)
        server.set_dpi.assert_called_once_with(120, 144)


class SharingLayoutTest(unittest.TestCase):

    def test_unsupported_layout_is_disabled(self):
        # only the seamless X11 servers can give each client its own area of the display,
        # everything else must fall back to sharing it as `sharing=yes` would
        from xpra.server.subsystem.display import DisplayManager
        opts = AdHocStruct()
        opts.dpi = 96
        opts.refresh_rate = "auto"
        opts.sharing = "combine"
        server = AdHocStruct()
        server.hello_request_handlers = {}
        server.session_type = "test"
        dm = stubbable(DisplayManager)(server)
        dm.init(opts)
        self.assertEqual(dm.sharing_layout, "combine")
        self.assertFalse(DisplayManager.SHARING_LAYOUT_SUPPORTED)
        dm.disable_sharing_layout("testing")
        self.assertEqual(dm.sharing_layout, "")

    def test_no_layout(self):
        from xpra.server.subsystem.display import DisplayManager
        opts = AdHocStruct()
        opts.dpi = 96
        opts.refresh_rate = "auto"
        server = AdHocStruct()
        server.hello_request_handlers = {}
        for sharing in ("yes", "no", "auto", "sync"):
            with self.subTest(sharing=sharing):
                opts.sharing = sharing
                dm = stubbable(DisplayManager)(server)
                dm.init(opts)
                self.assertEqual(dm.sharing_layout, "")


def main():
    unittest.main()


if __name__ == '__main__':
    main()
