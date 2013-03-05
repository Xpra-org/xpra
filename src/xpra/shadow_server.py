# coding=utf8
# This file is part of Parti.
# Copyright (C) 2012-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk

from wimpiggy.log import Logger
log = Logger()

from xpra.x11_server_base import X11ServerBase
from xpra.shadow_server_base import ShadowServerBase


def has_compositor(display):
    try:
        from wimpiggy.lowlevel.bindings import const,myGetSelectionOwner        #@UnresolvedImport
        from wimpiggy.error import trap, XError                                 #@UnresolvedImport
    except Exception, e:
        raise Exception("failed to load bindings: %s" % e)
    try:
        owner = trap.call_synced(myGetSelectionOwner, display, "_NET_WM_CM_S0")
        log("compositor: %s", owner)
        return owner and owner!=const["XNone"]
    except XError, e:
        raise Exception("error testing for compositing window manager: %s" % e)


class XpraX11ShadowServer(ShadowServerBase, X11ServerBase):

    def __init__(self, sockets, opts):
        ShadowServerBase.__init__(self)
        X11ServerBase.__init__(self, True, sockets, opts)
        display = gtk.gdk.display_get_default()
        log("display=%s", display)
        if display.supports_composite() and has_compositor(display):
            log.warn("display %s uses a compositing window manager, shadowing may not work as expected - sorry" % display.get_name())

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        #adjust pointer position for offset in client:
        x, y = pointer
        wx, wy = self.mapped_at[:2]
        pointer = x-wx, y-wy
        X11ServerBase._process_mouse_common(self, proto, wid, pointer, modifiers)

    def make_hello(self):
        capabilities = X11ServerBase.make_hello(self)
        capabilities["shadow"] = True
        capabilities["server_type"] = "gtk-shadow"
        return capabilities

    def get_info(self, proto):
        info = X11ServerBase.get_info(self, proto)
        info["shadow"] = True
        info["server_type"] = "gtk-shadow"
        return info
