# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
import gtk
from gtk import gdk
import cairo

from xpra.log import Logger
log = Logger("window")

from xpra.client.gtk_base.gtk_client_window_base import GTKClientWindowBase, HAS_X11_BINDINGS
from xpra.client.gtk2.window_backing import HAS_ALPHA

#optional module providing faster handling of premultiplied argb:
try:
    from xpra.codecs.argb.argb import unpremultiply_argb, byte_buffer_to_buffer   #@UnresolvedImport
except:
    unpremultiply_argb, byte_buffer_to_buffer  = None, None


GTK2_WINDOW_EVENT_MASK = gdk.STRUCTURE_MASK | gdk.KEY_PRESS_MASK | gdk.KEY_RELEASE_MASK \
            | gdk.POINTER_MOTION_MASK | gdk.BUTTON_PRESS_MASK | gdk.BUTTON_RELEASE_MASK \
            | gdk.PROPERTY_CHANGE_MASK
GTK2_OR_TYPE_HINTS = [gdk.WINDOW_TYPE_HINT_DIALOG,
                gdk.WINDOW_TYPE_HINT_MENU, gdk.WINDOW_TYPE_HINT_TOOLBAR,
                #gdk.WINDOW_TYPE_HINT_SPLASHSCREEN, gdk.WINDOW_TYPE_HINT_UTILITY,
                #gdk.WINDOW_TYPE_HINT_DOCK, gdk.WINDOW_TYPE_HINT_DESKTOP,
                gdk.WINDOW_TYPE_HINT_DROPDOWN_MENU, gdk.WINDOW_TYPE_HINT_POPUP_MENU,
                gdk.WINDOW_TYPE_HINT_TOOLTIP,
                #gdk.WINDOW_TYPE_HINT_NOTIFICATION,
                gdk.WINDOW_TYPE_HINT_COMBO,gdk.WINDOW_TYPE_HINT_DND]
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

    #must be overriden by subclasses
    BACKING_CLASS = None

    def init_window(self, metadata):
        if self._override_redirect:
            gtk.Window.__init__(self, gtk.WINDOW_POPUP)
        else:
            gtk.Window.__init__(self, gtk.WINDOW_TOPLEVEL)
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

    def set_alpha(self):
        #by default, only RGB (no transparency):
        self._client_properties["encodings.rgb_formats"] = ["RGB", "RGBX"]
        if not HAS_ALPHA:
            self._client_properties["encoding.transparency"] = False
            self._has_alpha = False
            return
        if self._has_alpha and not self.is_realized():
            screen = self.get_screen()
            rgba = screen.get_rgba_colormap()
            if rgba is None:
                self._has_alpha = False
                self._client_properties["encoding.transparency"] = False
                log.error("cannot handle window transparency on screen %s", screen)
            else:
                log("set_alpha() using rgba colormap for %s, realized=%s", self._id, self.is_realized())
                self.set_colormap(rgba)
                self._client_properties["encodings.rgb_formats"] = ["RGBA", "RGB", "RGBX"]

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
        except Exception, e:
            log.error("xget_u32_property error on %s / %s: %s", target, name, e)
        return GTKClientWindowBase.xget_u32_property(self, target, name)

    def get_desktop_workspace(self):
        window = self.gdk_window()
        root = window.get_screen().get_root_window()
        return self.do_get_workspace(root, "_NET_CURRENT_DESKTOP")

    def get_window_workspace(self):
        return self.do_get_workspace(self.gdk_window(), "_NET_WM_DESKTOP")

    def do_get_workspace(self, target, prop):
        if sys.platform.startswith("win") or sys.platform.startswith("darwin"):
            return  -1              #windows and OSX do not have workspaces
        value = self.xget_u32_property(target, prop)
        if value==(2**32-1):
            value = -1
        if value is not None:
            log("do_get_workspace() found value=%s from %s / %s", value, target, prop)
            return value
        log("do_get_workspace() value not found!")
        return  -1


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
        return x, y, w, h

    def apply_geometry_hints(self, hints):
        self.set_geometry_hints(None, **hints)

    def queue_draw(self, x, y, width, height):
        window = self.gdk_window()
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


    def update_icon(self, width, height, coding, data):
        log("%s.update_icon(%s, %s, %s, %s bytes)", self, width, height, coding, len(data))
        if coding == "premult_argb32":
            if unpremultiply_argb is not None:
                #we usually cannot do in-place and this is not performance critical
                data = byte_buffer_to_buffer(unpremultiply_argb(data))
                pixbuf = gdk.pixbuf_new_from_data(data, gtk.gdk.COLORSPACE_RGB, True, 8, width, height, width*4)
            else:
                # slower fallback: we round-trip through PNG.
                # This is ridiculous, but faster than doing a bunch of alpha
                # un-premultiplying and byte-swapping by hand in Python
                cairo_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                cairo_surf.get_data()[:] = data
                loader = gdk.PixbufLoader()
                cairo_surf.write_to_png(loader)
                loader.close()
                pixbuf = loader.get_pixbuf()
        else:
            loader = gdk.PixbufLoader(coding)
            loader.write(data, len(data))
            loader.close()
            pixbuf = loader.get_pixbuf()
        self.set_icon(pixbuf)
