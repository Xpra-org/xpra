# This file is part of Parti.
# Copyright (C) 2008, 2009 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#@PydevCodeAnalysisIgnore

from wimpiggy.test import *
import parti.bus
import gtk

class TestDBus(TestWithSession):
    def test_spawn_repl_window(self):
        class MockWm(object):
            def __init__(self):
                self.called = False
            def spawn_repl_window(self):
                print("spawn_repl_window called on server")
                self.called = True
        wm = MockWm()
        service = parti.bus.PartiDBusService(wm)
        proxy = parti.bus.get_parti_proxy()
        self.error = False
        def replied():
            print("got reply")
            gtk.main_quit()
        def errored():
            print("got error")
            self.error = True
            gtk.main_quit()
        proxy.SpawnReplWindow(reply_handler=replied,
                              error_handler=errored)
        assert not wm.called
        gtk.main()
        print("mainloop exited")
        assert not self.error
        assert wm.called
