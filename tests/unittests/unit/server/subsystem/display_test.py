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
