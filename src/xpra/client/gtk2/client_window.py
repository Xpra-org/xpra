# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gobject
import gtk
from gtk import gdk

from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, DRAW_DEBUG, HAS_X11_BINDINGS
from xpra.log import Logger
log = Logger()


"""
GTK2 version of the ClientWindow class
"""
class ClientWindow(GTKClientWindowBase):

    WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK \
            | gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK \
            | gdk.PROPERTY_CHANGE_MASK

    OR_TYPE_HINTS = [gdk.WINDOW_TYPE_HINT_DIALOG,
                gdk.WINDOW_TYPE_HINT_MENU, gdk.WINDOW_TYPE_HINT_TOOLBAR,
                #gdk.WINDOW_TYPE_HINT_SPLASHSCREEN, gdk.WINDOW_TYPE_HINT_UTILITY,
                #gdk.WINDOW_TYPE_HINT_DOCK, gdk.WINDOW_TYPE_HINT_DESKTOP,
                gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU, gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                gdk.WINDOW_TYPE_HINT_TOOLTIP,
                #gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                gdk.WINDOW_TYPE_HINT_COMBO,gdk.WINDOW_TYPE_HINT_DND]
    NAME_TO_HINT = {
                "_NET_WM_WINDOW_TYPE_NORMAL"        : gdk.WINDOW_TYPE_HINT_NORMAL,
                "_NET_WM_WINDOW_TYPE_DIALOG"        : gdk.WINDOW_TYPE_HINT_DIALOG,
                "_NET_WM_WINDOW_TYPE_MENU"          : gdk.WINDOW_TYPE_HINT_MENU,
                "_NET_WM_WINDOW_TYPE_TOOLBAR"       : gdk.WINDOW_TYPE_HINT_TOOLBAR,
                "_NET_WM_WINDOW_TYPE_SPLASH"        : gdk.WINDOW_TYPE_HINT_SPLASHSCREEN,
                "_NET_WM_WINDOW_TYPE_UTILITY"       : gdk.WINDOW_TYPE_HINT_UTILITY,
                "_NET_WM_WINDOW_TYPE_DOCK"          : gdk.WINDOW_TYPE_HINT_DOCK,
                "_NET_WM_WINDOW_TYPE_DESKTOP"       : gdk.WINDOW_TYPE_HINT_DESKTOP,
                "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU" : gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU,
                "_NET_WM_WINDOW_TYPE_POPUP_MENU"    : gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                "_NET_WM_WINDOW_TYPE_TOOLTIP"       : gdk.WINDOW_TYPE_HINT_TOOLTIP,
                "_NET_WM_WINDOW_TYPE_NOTIFICATION"  : gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                "_NET_WM_WINDOW_TYPE_COMBO"         : gdk.WINDOW_TYPE_HINT_COMBO,
                "_NET_WM_WINDOW_TYPE_DND"           : gdk.WINDOW_TYPE_HINT_DND
                }
    # Map scroll directions back to mouse buttons.  Mapping is taken from
    # gdk/x11/gdkevents-x11.c.
    SCROLL_MAP = {gdk.SCROLL_UP: 4,
                  gdk.SCROLL_DOWN: 5,
                  gdk.SCROLL_LEFT: 6,
                  gdk.SCROLL_RIGHT: 7,
                  }

    def init_window(self, metadata):
        if self._override_redirect:
            gtk.Window.__init__(self, gtk.WINDOW_POPUP)
        else:
            gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        GTKClientWindowBase.init_window(self, metadata)

    def xget_u32_property(self, target, name):
        try:
            if not HAS_X11_BINDINGS:
                prop = target.property_get(name)
                if not prop or len(prop)!=3 or len(prop[2])!=1:
                    return  None
                log("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
                return prop[2][0]
        except Exception, e:
            log.error("xget_u32_property error on %s / %s: %s", target, name, e)
        return GTKClientWindowBase.xget_u32_property(self, target, name)

    def is_mapped(self):
        return self.window is not None and self.window.is_visible()

    def gdk_window(self):
        if gtk.gtk_version>=(2,14):
            return self.get_window()
        else:
            return self.window

    def get_window_geometry(self):
        gdkwindow = self.gdk_window()
        x, y = gdkwindow.get_origin()
        _, _, w, h, _ = gdkwindow.get_geometry()
        return (x, y, w, h)

    def apply_geometry_hints(self, hints):
        self.set_geometry_hints(None, **hints)

    def queue_draw(self, x, y, width, height):
        window = self.gdk_window()
        if window:
            window.invalidate_rect(gdk.Rectangle(x, y, width, height), False)
        else:
            log.warn("ignoring draw received for a window which is not realized yet!")

    def do_expose_event(self, event):
        if DRAW_DEBUG:
            log.info("do_expose_event(%s) area=%s", event, event.area)
        if not (self.flags() & gtk.MAPPED) or self._backing is None:
            return
        context = self.window.cairo_create()
        context.rectangle(event.area)
        context.clip()
        self._backing.cairo_draw(context)
        if not self._client.server_ok():
            self.paint_spinner(context, event.area)


gobject.type_register(ClientWindow)
