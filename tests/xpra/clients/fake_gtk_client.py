#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2012 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.gtk.util import get_default_root_window
from tests.xpra.clients.fake_client import FakeClient

Gtk = gi_import("Gtk")


class FakeGTKClient(FakeClient):

    def __init__(self):
        FakeClient.__init__(self)

    def get_mouse_position(self, *_args):
        root = get_default_root_window()
        p = root.get_pointer()
        return p[0], p[1]

    def get_current_modifiers(self, *_args):
        #root = gdk.get_default_root_window()
        #modifiers_mask = root.get_pointer()[-1]
        #return self.mask_to_names(modifiers_mask)
        return []

    def window_close_event(self, *_args):
        Gtk.main_quit()

    def server_ok(self):
        return True


def gtk_main():
    Gtk.main()
