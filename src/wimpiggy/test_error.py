# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
from wimpiggy.error import trap, XError
# Need a way to generate X errors...
import wimpiggy.lowlevel

import gtk.gdk

class TestError(TestWithSession):
    def cause_badwindow(self):
        root = self.display.get_default_screen().get_root_window()
        win = gtk.gdk.Window(root, width=10, height=10,
                             window_type=gtk.gdk.WINDOW_TOPLEVEL,
                             wclass=gtk.gdk.INPUT_OUTPUT,
                             event_mask=0)
        win.destroy()
        wimpiggy.lowlevel.XAddToSaveSet(win)
        return 3

    def test_call(self):
        assert trap.call(lambda: 0) == 0
        assert trap.call(lambda: 1) == 1
        try:
            trap.call(self.cause_badwindow)
        except XError, e:
            assert e.args == (wimpiggy.lowlevel.const["BadWindow"],)

    def test_swallow(self):
        assert trap.swallow(lambda: 0) is None
        assert trap.swallow(lambda: 1) is None
        assert trap.swallow(self.cause_badwindow) is None

    def test_assert_out(self):
        def foo():
            assert_raises(AssertionError, trap.assert_out)
        trap.call(foo)
