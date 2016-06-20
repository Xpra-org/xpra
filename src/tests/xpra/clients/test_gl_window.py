#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()


import gtk
from gtk import gdk
import glib

from xpra.util import typedict
from tests.xpra.clients.fake_client import FakeClient
from xpra.client.gl.gtk2.gl_client_window import GLClientWindow

from xpra.codecs.loader import load_codecs

load_codecs(encoders=False, decoders=True, csc=False)

def get_mouse_position(*args):
    root = gdk.get_default_root_window()
    p = root.get_pointer()
    return p[0], p[1]

def get_current_modifiers(*args):
    #root = gdk.get_default_root_window()
    #modifiers_mask = root.get_pointer()[-1]
    #return self.mask_to_names(modifiers_mask)
    return []

client = FakeClient()
client.get_mouse_position = get_mouse_position
client.get_current_modifiers = get_current_modifiers
client.source_remove = glib.source_remove
client.timeout_add = glib.timeout_add
client.idle_add = glib.idle_add

W = 640
H = 480
window = GLClientWindow(client, None, 1, 10, 10, W, H, W, H, typedict({}), False, typedict({}), 0, None)
window.show()
def paint_window():
    img_data = "\0"*W*3*H
    window.draw_region(0, 0, W, H, "rgb24", img_data, W*3, 0, typedict({}), [])

glib.timeout_add(1000, paint_window)

gtk.main()
