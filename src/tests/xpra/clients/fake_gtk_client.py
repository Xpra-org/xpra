#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import glib             #@UnresolvedImport
import gtk              #@UnresolvedImport
from gtk import gdk     #@UnresolvedImport

from tests.xpra.clients.fake_client import FakeClient


class FakeGTKClient(FakeClient):

    def __init__(self):
        FakeClient.__init__(self)
        self.source_remove = glib.source_remove
        self.timeout_add = glib.timeout_add
        self.idle_add = glib.idle_add

    def get_mouse_position(self, *_args):
        root = gdk.get_default_root_window()
        p = root.get_pointer()
        return p[0], p[1]

    def get_current_modifiers(self, *_args):
        #root = gdk.get_default_root_window()
        #modifiers_mask = root.get_pointer()[-1]
        #return self.mask_to_names(modifiers_mask)
        return []
    def window_close_event(self, *_args):
        gtk.main_quit()

    def server_ok(self):
        return True


def gtk_main():
    gtk.main()
