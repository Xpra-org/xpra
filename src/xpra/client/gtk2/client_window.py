# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from xpra.client.gtk2.gtk2_window_base import GTK2WindowBase, HAS_ALPHA
from xpra.codecs.video_helper import getVideoHelper

from xpra.log import Logger
log = Logger("opengl", "window")


USE_CAIRO = os.environ.get("XPRA_USE_CAIRO_BACKING", "0")=="1"
if USE_CAIRO:
    from xpra.client.gtk_base.cairo_backing import CairoBacking
    BACKING_CLASS = CairoBacking
else:
    from xpra.client.gtk2.pixmap_backing import PixmapBacking
    BACKING_CLASS = PixmapBacking


"""
Actual instantiable plain GTK2 Client Window
"""
class ClientWindow(GTK2WindowBase):

    full_csc_modes = None
    csc_modes = None

    def setup_window(self):
        self._client_properties["encoding.full_csc_modes"] = self.get_full_csc_modes()
        self._client_properties["encoding.csc_modes"] = self.get_csc_modes()
        GTK2WindowBase.setup_window(self)

    def new_backing(self, w, h):
        self._backing = self.make_new_backing(BACKING_CLASS, w, h)

    def get_full_csc_modes(self):
        #initialize just once per class
        if ClientWindow.full_csc_modes is None:
            #plain GTK2 window needs to use CSC modules to paint video
            #so calculate the server CSC modes the server is allowed to use
            #based on the client CSC modes we can convert to RGB(A):
            target_rgb_modes = BACKING_CLASS.RGB_MODES
            if not HAS_ALPHA:
                target_rgb_modes = [x for x in target_rgb_modes if x.find("A")<0]
            ClientWindow.full_csc_modes = getVideoHelper().get_server_full_csc_modes_for_rgb(*target_rgb_modes)
            log("full csc modes (%s)=%s", target_rgb_modes, ClientWindow.full_csc_modes)
        return ClientWindow.full_csc_modes

    def get_csc_modes(self):
        #initialize just once per class
        if ClientWindow.csc_modes is None:
            csc_modes = []
            for modes in self.get_full_csc_modes().values():
                csc_modes += modes
            ClientWindow.csc_modes = list(set(csc_modes))
        return ClientWindow.csc_modes
