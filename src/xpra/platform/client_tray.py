# This file is part of Parti.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.gobject_compat import import_gtk, is_gtk3
gtk = import_gtk()

from wimpiggy.log import Logger
log = Logger()

from xpra.window_backing import make_new_backing, PixmapBacking

ORIENTATION = {}
if not is_gtk3():
    #where was this moved to??
    HORIZONTAL  = gtk.ORIENTATION_HORIZONTAL
    VERTICAL    = gtk.ORIENTATION_VERTICAL
else:
    VERTICAL = "VERTICAL"
    HORIZONTAL = "HORIZONTAL"
ORIENTATION = {HORIZONTAL   : "HORIZONTAL",
               VERTICAL     : "VERTICAL"}


class ClientTray(object):
    def __init__(self, client, wid, w, h):
        self._client = client
        self._id = wid
        self._geometry = None
        self._screen = -1
        self._orientation = VERTICAL
        self.group_leader = None

        self._backing = None
        self.tray_widget = gtk.StatusIcon()
        self.tray_widget.set_from_stock(gtk.STOCK_INFO)
        self.tray_widget.connect('popup-menu', self.popup_menu)
        self.tray_widget.connect('activate', self.activate_menu)
        self.tray_widget.connect('size-changed', self.size_changed)
        self.tray_widget.set_visible(True)
        self.may_configure()

    def is_OR(self):
        return True

    def is_tray(self):
        return True

    def is_GL(self):
        return False

    def get_window(self):
        return None

    def may_configure(self, force=False):
        #this function may be called numerous times from both init
        #and from events because the statusicon's geometry is not
        #reliable.. and later calls are more likely to be correct.
        ag = self.tray_widget.get_geometry()
        if ag:
            screen, geom, orientation = ag
            geometry = geom.x, geom.y, geom.width, geom.height
            if self._geometry is None or self._geometry!=geometry:
                self._geometry = geometry
                self._screen = screen.get_number()
                self._orientation = orientation
                log("may_configure: geometry=%s, current geometry=%s", geometry, self._geometry)
                self.reconfigure()
        elif self._geometry is None:
            #probably a platform that does not support geometry.. oh well
            self._geometry = 200, 0, 48, 48
            self.reconfigure()

    def reconfigure(self):
        client_properties = {"orientation" : ORIENTATION.get(self._orientation, self._orientation)}
        if self._screen>=0:
            client_properties["screen"] = self._screen
        x, y, w, h = self._geometry
        if self._geometry!=(0, 0, 200, 200):
            self._client.send("configure-window", self._id, x, y, w, h, client_properties)
        self.new_backing(w, h)

    def move_resize(self, x, y, w, h):
        log("move_resize(%s, %s, %s, %s)", x, y, w, h)
        w = max(1, w)
        h = max(1, h)
        self._geometry = x, y, w, h
        self.reconfigure()

    def new_backing(self, w, h):
        self._backing = make_new_backing(PixmapBacking, self._id, w, h, self._backing, self._client.supports_mmap, self._client.mmap)
        self._size = w, h

    def size_changed(self, status_icon, size):
        log("ClientTray.size_changed(%s, %s)", status_icon, size)

    def update_metadata(self, metadata):
        log("update_metadata(%s)", metadata)

    def update_icon(self, width, height, coding, data):
        pass

    def activate_menu(self, widget, *args):
        log("activate_menu(%s, %s)", widget, args)
        self._button_action(1, 1)
        self._button_action(1, 0)

    def popup_menu(self, widget, button, time, *args):
        log("popup_menu(%s, %s, %s, %s)", widget, button, time, args)
        self._button_action(button, 1)
        self._button_action(button, 0)

    def _button_action(self, button, depressed):
        if self._client.readonly:
            return
        self.may_configure()
        root = gtk.gdk.get_default_root_window()
        x, y, modifiers_mask = root.get_pointer()
        modifiers = self._client.mask_to_names(modifiers_mask)
        log("packet: %s", ["button-action", self._id,
                                      button, depressed,
                                      (x, y), modifiers])
        self._client.send_positional(["button-action", self._id,
                                      button, depressed,
                                      (x, y), modifiers])

    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        assert coding in ("rgb24", "png", "mmap"), "invalid encoding for tray data: %s" % coding
        log("draw_region for tray")
        def after_draw_update_tray(success):
            if not success:
                log.warn("after_draw_update_tray(%s) options=%s", success, options)
                return
            w, h = self._size
            pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, True, 8, w, h)
            tray_icon = pixbuf.get_from_drawable(self._backing._backing, self._backing._backing.get_colormap(),
                                      0, 0, 0, 0, w, h)
            size = self.tray_widget.get_size()
            if size!=w or size!=h:
                tray_icon = tray_icon.scale_simple(size, size, gtk.gdk.INTERP_HYPER)
            log("after_draw_update_tray(%s) tray icon=%s, size=%s", success, tray_icon, size)
            self.tray_widget.set_from_pixbuf(tray_icon)
            self.may_configure()
        callbacks.append(after_draw_update_tray)
        self._backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def destroy(self):
        self.tray_widget.set_visible(False)
        self.tray_widget = None
