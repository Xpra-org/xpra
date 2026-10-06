#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import unittest

from xpra.client.gui.window_border import WindowBorder


class AuthHandlersTest(unittest.TestCase):

    def test_toggle(self):
        b = WindowBorder(shown=True)
        b.toggle()
        assert b.shown is False

    def test_clone(self):
        b = WindowBorder(red=1, blue=0, green=1, alpha=0.5, size=10)
        b2 = b.clone()
        assert b.red==b2.red
        assert b.blue==b2.blue
        assert b.green==b2.green
        assert b.alpha==b2.alpha
        assert b.size==b2.size

    def test_repr(self):
        b = WindowBorder(red=0, blue=1, green=0.5)
        assert repr(b).find("00")>=0
        assert repr(b).find("FF")>=0

    def test_update(self):
        b = WindowBorder(shown=False)
        b.update(WindowBorder(red=0, green=1, blue=0, alpha=0.5, size=10))
        assert b.shown and b.green == 1 and b.alpha == 0.5 and b.size == 10


class ServerBorderTest(unittest.TestCase):

    @staticmethod
    def make_client(border: str):
        from xpra.common import noop
        from xpra.util.objects import AdHocStruct
        from xpra.client.base.stub import StubClientSubsystem
        from xpra.client.subsystem.window.border import WindowBorderClient

        class TestBorderClient(WindowBorderClient):
            __slots__ = WindowBorderClient.SLOT_NAMES + ("_id_to_window", )

            def __init__(self, client):
                StubClientSubsystem.__init__(self, client)
                WindowBorderClient.__init__(self)
                self._id_to_window = {}

        callbacks = {}
        client = AdHocStruct()
        client.display_desc = {"display_name": ":100"}
        client.idle_add = client.timeout_add = client.source_remove = noop
        client.on_server_setting_changed = lambda setting, cb: callbacks.setdefault(setting, cb)
        bc = TestBorderClient(client)
        opts = AdHocStruct()
        opts.border = border
        bc.init(opts)
        bc.setup_connection(None)
        return bc, callbacks

    def test_default_uses_server_border(self):
        from xpra.util.objects import typedict
        from xpra.scripts.config import DEFAULT_BORDER
        bc, callbacks = self.make_client(DEFAULT_BORDER)
        assert not bc.border.shown
        bc.parse_server_capabilities(typedict({"border": "red,10"}))
        assert bc.border.shown and bc.border.size == 10
        assert bc.border.red > 0.9 and bc.border.green == 0
        # a window created earlier is updated in place:
        from xpra.util.objects import AdHocStruct
        window = AdHocStruct()
        window.border = bc.get_border()
        redraws = []
        window.redraw_border = lambda: redraws.append(True)
        bc._id_to_window[1] = window
        callbacks["border"]("border", "blue,3")
        assert window.border.size == 3 and window.border.blue > 0.9
        assert redraws
        callbacks["border"]("border", "no")
        assert not window.border.shown

    def test_client_border_wins(self):
        from xpra.util.objects import typedict
        bc, callbacks = self.make_client("blue,7")
        bc.parse_server_capabilities(typedict({"border": "red,10"}))
        assert bc.border.size == 7 and bc.border.blue > 0.9
        assert "border" not in callbacks


def main():
    unittest.main()


if __name__ == '__main__':
    main()
