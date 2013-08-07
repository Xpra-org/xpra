# This file is part of Xpra.
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.client_widget_base import ClientWidgetBase
from xpra.log import Logger
log = Logger()

from xpra.client.gtk2.pixmap_backing import GTK2WindowBacking


class ClientTray(ClientWidgetBase):
    """
        This acts like a widget and we use the TrayBacking
        to capture the tray pixels and forward them
        to the real tray widget class.
    """

    def __init__(self, client, wid, w, h, tray_widget):
        ClientWidgetBase.__init__(self, client, wid)
        self.tray_widget = tray_widget
        self._has_alpha = True
        self._geometry = None
        self.group_leader = None

        self._backing = None
        self.new_backing(w, h)
        self.idle_add(self.reconfigure)

    def is_OR(self):
        return True

    def is_tray(self):
        return True

    def get_window(self):
        return None

    def reconfigure(self):
        geometry = self.tray_widget.get_geometry()
        if geometry is None:
            #make one up!
            geometry = 0, 0, 64, 64
        x, y, w, h = geometry
        if w<=1 or h<=1:
            w, h = 64, 64
            geometry = x, y, w, h
        if self._geometry is None or geometry!=self._geometry:
            self._geometry = geometry
            client_properties = {"encoding.transparency": True}
            orientation = self.tray_widget.get_orientation()
            if orientation:
                client_properties["orientation"] = orientation
            screen = self.tray_widget.get_screen()
            if screen>=0:
                client_properties["screen"] = screen
            self._client.send("configure-window", self._id, x, y, w, h, client_properties)
        if self._size!=(w, h):
            self.new_backing(w, h)

    def move_resize(self, x, y, w, h):
        log("move_resize(%s, %s, %s, %s)", x, y, w, h)
        w = max(1, w)
        h = max(1, h)
        self._geometry = x, y, w, h
        self.reconfigure()

    def new_backing(self, w, h):
        self._size = w, h
        self._backing = TrayBacking(self._id, w, h, self._has_alpha)

    def update_metadata(self, metadata):
        log("update_metadata(%s)", metadata)

    def update_icon(self, width, height, coding, data):
        #this is the window icon... not the tray icon!
        pass


    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        assert coding in ("rgb24", "rgb32", "png", "mmap", "webp"), "invalid encoding for tray data: %s" % coding
        log("ClientTray.draw_region(%s)", [x, y, width, height, coding, "%s bytes" % len(img_data), rowstride, packet_sequence, options, callbacks])

        def after_draw_update_tray(success):
            if not success:
                log.warn("after_draw_update_tray(%s) options=%s", success, options)
                return
            if not self._backing.pixels:
                log.warn("TrayBacking does not have any pixels / format!")
                return
            self.set_tray_icon()
            self.idle_add(self.reconfigure)
        callbacks.append(after_draw_update_tray)
        self._backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def set_tray_icon(self):
        log("set_tray_icon() format=%s", self._backing.format)
        enc, w, h, rowstride = self._backing.format
        has_alpha = enc=="rgb32"
        self.tray_widget.set_icon_from_data(self._backing.pixels, has_alpha, w, h, rowstride)
        

    def destroy(self):
        if self.tray_widget:
            self.tray_widget.cleanup()
            self.tray_widget = None


class TrayBacking(GTK2WindowBacking):
    """
        This backing only stores the rgb pixels so
        we can use them with the real widget.
    """

    def __init__(self, wid, w, h, has_alpha):
        self.pixels = None
        self.format = None
        GTK2WindowBacking.__init__(self, wid, w, h, has_alpha)

    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options, callbacks):
        self.pixels = img_data
        self.format = ("rgb24", width, height, rowstride)
        return True

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options, callbacks):
        self.pixels = img_data
        self.format = ("rgb32", width, height, rowstride)
        return True
