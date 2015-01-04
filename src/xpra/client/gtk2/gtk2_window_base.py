# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2014 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk
from gtk import gdk

from xpra.log import Logger
log = Logger("window")

from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.client.client_window_base import WORKSPACE_UNSET
from xpra.platform.gui import add_window_hooks, remove_window_hooks


GTK2_WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK \
            | gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK \
            | gdk.PROPERTY_CHANGE_MASK
GTK2_OR_TYPE_HINTS = (gdk.WINDOW_TYPE_HINT_DIALOG,
                gdk.WINDOW_TYPE_HINT_MENU, gdk.WINDOW_TYPE_HINT_TOOLBAR,
                #gdk.WINDOW_TYPE_HINT_SPLASHSCREEN,
                #gdk.WINDOW_TYPE_HINT_UTILITY,
                gdk.WINDOW_TYPE_HINT_DOCK,
                #gdk.WINDOW_TYPE_HINT_DESKTOP,
                gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU,
                gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                gdk.WINDOW_TYPE_HINT_TOOLTIP,
                #gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                gdk.WINDOW_TYPE_HINT_COMBO,
                gdk.WINDOW_TYPE_HINT_DND)
GTK2_NAME_TO_HINT = {
                "NORMAL"        : gdk.WINDOW_TYPE_HINT_NORMAL,
                "DIALOG"        : gdk.WINDOW_TYPE_HINT_DIALOG,
                "MENU"          : gdk.WINDOW_TYPE_HINT_MENU,
                "TOOLBAR"       : gdk.WINDOW_TYPE_HINT_TOOLBAR,
                "SPLASH"        : gdk.WINDOW_TYPE_HINT_SPLASHSCREEN,
                "UTILITY"       : gdk.WINDOW_TYPE_HINT_UTILITY,
                "DOCK"          : gdk.WINDOW_TYPE_HINT_DOCK,
                "DESKTOP"       : gdk.WINDOW_TYPE_HINT_DESKTOP,
                "DROPDOWN_MENU" : gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU,
                "POPUP_MENU"    : gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                "TOOLTIP"       : gdk.WINDOW_TYPE_HINT_TOOLTIP,
                "NOTIFICATION"  : gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                "COMBO"         : gdk.WINDOW_TYPE_HINT_COMBO,
                "DND"           : gdk.WINDOW_TYPE_HINT_DND
                }
GTK2_BUTTON_MASK = {gtk.gdk.BUTTON1_MASK : 1,
                    gtk.gdk.BUTTON2_MASK : 2,
                    gtk.gdk.BUTTON3_MASK : 3,
                    gtk.gdk.BUTTON4_MASK : 4,
                    gtk.gdk.BUTTON5_MASK : 5}
# Map scroll directions back to mouse buttons.  Mapping is taken from
# gdk/x11/gdkevents-x11.c.
GTK2_SCROLL_MAP = {
                   gdk.SCROLL_UP: 4,
                   gdk.SCROLL_DOWN: 5,
                   gdk.SCROLL_LEFT: 6,
                   gdk.SCROLL_RIGHT: 7,
                  }



"""
GTK2 version of the ClientWindow class
"""
class GTK2WindowBase(GTKClientWindowBase):

    WINDOW_EVENT_MASK   = GTK2_WINDOW_EVENT_MASK
    OR_TYPE_HINTS       = GTK2_OR_TYPE_HINTS
    NAME_TO_HINT        = GTK2_NAME_TO_HINT
    SCROLL_MAP          = GTK2_SCROLL_MAP
    BUTTON_MASK         = GTK2_BUTTON_MASK

    WINDOW_STATE_FULLSCREEN = gdk.WINDOW_STATE_FULLSCREEN
    WINDOW_STATE_MAXIMIZED  = gdk.WINDOW_STATE_MAXIMIZED
    WINDOW_STATE_ICONIFIED  = gdk.WINDOW_STATE_ICONIFIED
    WINDOW_STATE_ABOVE      = gdk.WINDOW_STATE_ABOVE
    WINDOW_STATE_BELOW      = gdk.WINDOW_STATE_BELOW
    WINDOW_STATE_STICKY     = gdk.WINDOW_STATE_STICKY


    def init_window(self, metadata):
        if self._is_popup(metadata):
            gtk.Window.__init__(self, gtk.WINDOW_POPUP)
        else:
            gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
        self.set_decorated(self._is_decorated(metadata))
        GTKClientWindowBase.init_window(self, metadata)
        # tell KDE/oxygen not to intercept clicks
        # see: https://bugs.kde.org/show_bug.cgi?id=274485
        self.set_data("_kde_no_window_grab", 1)


    def setup_window(self):
        #preserve screen:
        if not self._override_redirect:
            display = gtk.gdk.display_get_default()
            screen_num = self._client_properties.get("screen", -1)
            n = display.get_n_screens()
            log("setup_window() screen=%s, nscreens=%s", screen_num, n)
            if screen_num>=0 and screen_num<n:
                screen = display.get_screen(screen_num)
                if screen:
                    self.set_screen(screen)
        GTKClientWindowBase.setup_window(self)
        #add platform hooks
        self.connect("realize", self.on_realize)
        self.connect('unrealize', self.on_unrealize)

    def on_realize(self, widget):
        log("on_realize(%s)", widget)
        add_window_hooks(self)

    def on_unrealize(self, widget):
        log("on_unrealize(%s)", widget)
        remove_window_hooks(self)


    def enable_alpha(self):
        screen = self.get_screen()
        rgba = screen.get_rgba_colormap()
        if rgba is None:
            log.error("enable_alpha() cannot handle window transparency on screen %s", screen)
            return  False
        log("enable_alpha() using rgba colormap %s for wid %s", rgba, self._id)
        self.set_colormap(rgba)
        return True

    def set_modal(self, modal):
        #with gtk2 setting the window as modal would prevent
        #all other windows we manage from receiving input
        #including other unrelated applications
        #what we want is "window-modal"
        log("set_modal(%s) swallowed", modal)

    def xget_u32_property(self, target, name):
        try:
            if not HAS_X11_BINDINGS:
                prop = target.property_get(name)
                if not prop or len(prop)!=3 or len(prop[2])!=1:
                    return  None
                log("xget_u32_property(%s, %s)=%s", target, name, prop[2][0])
                return prop[2][0]
        except Exception as e:
            log.error("xget_u32_property error on %s / %s: %s", target, name, e)
        return GTKClientWindowBase.xget_u32_property(self, target, name)

    def get_desktop_workspace(self):
        window = self.get_window()
        if window:
            root = window.get_screen().get_root_window()
        else:
            #if we are called during init.. we don't have a window
            root = gtk.gdk.get_default_root_window()
        return self.do_get_workspace(root, "_NET_CURRENT_DESKTOP")

    def get_window_workspace(self):
        return self.do_get_workspace(self.get_window(), "_NET_WM_DESKTOP", WORKSPACE_UNSET)

    def do_get_workspace(self, target, prop, default_value=None):
        if not self._can_set_workspace:
            return  None              #windows and OSX do not have workspaces
        value = self.xget_u32_property(target, prop)
        if value is not None:
            log("do_get_workspace() found value=%s from %s / %s", value, target, prop)
            return value
        log("do_get_workspace() value not found!")
        return  default_value


    def is_mapped(self):
        return self.window is not None and self.window.is_visible()

    def get_window_geometry(self):
        gdkwindow = self.get_window()
        x, y = gdkwindow.get_origin()
        _, _, w, h, _ = gdkwindow.get_geometry()
        return x, y, w, h

    def apply_geometry_hints(self, hints):
        self.set_geometry_hints(None, **hints)

    def queue_draw(self, x, y, width, height):
        window = self.get_window()
        if window:
            window.invalidate_rect(gdk.Rectangle(x, y, width, height), False)
        else:
            log.warn("ignoring draw received for a window which is not realized yet!")

    def do_expose_event(self, event):
        #cannot use self
        log("do_expose_event(%s) area=%s", event, event.area)
        if not (self.flags() & gtk.MAPPED) or self._backing is None:
            return
        w,h = self.window.get_size()
        if w>=32768 or h>=32768:
            log.error("cannot paint on window which is too large: %sx%s !", w, h)
            return
        context = self.window.cairo_create()
        context.rectangle(event.area)
        context.clip()
        self._backing.cairo_draw(context)
        if not self._client.server_ok():
            self.paint_spinner(context, event.area)
