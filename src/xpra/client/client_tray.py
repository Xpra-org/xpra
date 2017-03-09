# This file is part of Xpra.
# Copyright (C) 2010-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.client.client_widget_base import ClientWidgetBase
from xpra.log import Logger
log = Logger("tray")

from xpra.client.gtk_base.gtk_window_backing_base import GTKWindowBacking


class ClientTray(ClientWidgetBase):
    """
        This acts like a widget and we use the TrayBacking
        to capture the tray pixels and forward them
        to the real tray widget class.
    """
    DEFAULT_LOCATION = [0, 0]
    DEFAULT_SIZE = [64, 64]
    DEFAULT_GEOMETRY = DEFAULT_LOCATION + DEFAULT_SIZE

    def __init__(self, client, wid, w, h, tray_widget, mmap_enabled, mmap_area):
        log("ClientTray%s", (client, wid, w, h, tray_widget, mmap_enabled, mmap_area))
        ClientWidgetBase.__init__(self, client, wid, True)
        self.tray_widget = tray_widget
        self._geometry = None
        self._window_alpha = True
        self.group_leader = None

        self.mmap_enabled = mmap_enabled
        self.mmap = mmap_area
        self._backing = None
        self.new_backing(w, h)
        self.idle_add(self.reconfigure)

    def get_backing_class(self):
        return TrayBacking

    def is_OR(self):
        return True

    def is_tray(self):
        return True

    def get_window(self):
        return None

    def get_geometry(self):
        return self._geometry or ClientTray.DEFAULT_GEOMETRY

    def get_tray_geometry(self):
        tw = self.tray_widget
        if not tw:
            return None
        return tw.get_geometry()

    def get_tray_size(self):
        tw = self.tray_widget
        if not tw:
            return None
        return tw.get_size()


    def freeze(self):
        pass


    def send_configure(self):
        self.reconfigure(True)

    def reconfigure(self, force_send_configure=False):
        geometry = None
        tw = self.tray_widget
        if tw:
            geometry = tw.get_geometry()
        log("%s.reconfigure(%s) geometry=%s", self, force_send_configure, geometry)
        if geometry is None:
            if self._geometry or not tw:
                geometry = self._geometry
            else:
                #make one up as best we can - maybe we have the size at least?
                size = tw.get_size()
                log("%s.reconfigure() guessing location using size=%s", self, size)
                geometry = ClientTray.DEFAULT_LOCATION + list(size or ClientTray.DEFAULT_SIZE)
        x, y, w, h = geometry
        if w<=1 or h<=1:
            w, h = ClientTray.DEFAULT_SIZE
            geometry = x, y, w, h
        if force_send_configure or self._geometry is None or geometry!=self._geometry:
            self._geometry = geometry
            client_properties = {"encoding.transparency": True,
                                 "encodings.rgb_formats" : ["RGBA", "RGB", "RGBX"]}
            if tw:
                orientation = tw.get_orientation()
                if orientation:
                    client_properties["orientation"] = orientation
                screen = tw.get_screen()
                if screen>=0:
                    client_properties["screen"] = screen
            #scale to server coordinates
            sx, sy, sw, sh = self._client.crect(x, y, w, h)
            log("%s.reconfigure(%s) sending configure for geometry=%s : %s", self, force_send_configure, geometry, (sx, sy, sw, sh, client_properties))
            self._client.send("configure-window", self._id, sx, sy, sw, sh, client_properties)
        if self._size!=(w, h):
            self.new_backing(w, h)

    def move_resize(self, x, y, w, h):
        log("%s.move_resize(%s, %s, %s, %s)", self, x, y, w, h)
        w = max(1, w)
        h = max(1, h)
        self._geometry = x, y, w, h
        self.reconfigure(True)

    def new_backing(self, w, h):
        self._size = w, h
        data = None
        if self._backing:
            data = self._backing.data
        self._backing = TrayBacking(self._id, w, h, self._has_alpha, data)
        if self.mmap_enabled:
            self._backing.enable_mmap(self.mmap)

    def update_metadata(self, metadata):
        log("%s.update_metadata(%s)", self, metadata)

    def update_icon(self, width, height, coding, data):
        #this is the window icon... not the tray icon!
        pass


    def draw_region(self, x, y, width, height, coding, img_data, rowstride, packet_sequence, options, callbacks):
        log("%s.draw_region%s", self, (x, y, width, height, coding, "%s bytes" % len(img_data), rowstride, packet_sequence, options, callbacks))

        #note: a new backing may be assigned between the time we call draw_region
        # and the time we get the callback (as the draw may use idle_add)
        backing = self._backing
        def after_draw_update_tray(success, message=None):
            log("%s.after_draw_update_tray(%s, %s)", self, success, message)
            if not success:
                log.warn("after_draw_update_tray(%s, %s) options=%s", success, message, options)
                return
            tray_data = backing.data
            log("tray backing=%s, data: %s", backing, tray_data is not None)
            if tray_data is None:
                log.warn("Warning: no pixel data in tray backing for window %i", backing.wid)
                return
            self.idle_add(self.set_tray_icon, tray_data)
            self.idle_add(self.reconfigure)
        callbacks.append(after_draw_update_tray)
        backing.draw_region(x, y, width, height, coding, img_data, rowstride, options, callbacks)

    def set_tray_icon(self, tray_data):
        enc, w, h, rowstride, pixels = tray_data
        log("%s.set_tray_icon(%s, %s, %s, %s, %s bytes)", self, enc, w, h, rowstride, len(pixels))
        has_alpha = enc=="rgb32"
        tw = self.tray_widget
        if tw:
            tw.set_icon_from_data(pixels, has_alpha, w, h, rowstride)


    def destroy(self):
        tw = self.tray_widget
        if tw:
            self.tray_widget = None
            tw.cleanup()

    def __repr__(self):
        return "ClientTray(%s)" % self._id


class TrayBacking(GTKWindowBacking):
    """
        This backing only stores the rgb pixels so
        we can use them with the real widget.
    """

    #keep it simple: only accept 32-bit RGB(X),
    #all tray implementations support alpha
    RGB_MODES = ["RGBA", "RGBX"]
    HAS_ALPHA = True

    def __init__(self, wid, w, h, has_alpha, data=None):
        self.data = data
        GTKWindowBacking.__init__(self, wid, True)
        self._backing = object()    #pretend we have a backing structure

    def get_encoding_properties(self):
        #override so we skip all csc caps:
        return {
                "encodings.rgb_formats" : self.RGB_MODES,
                "encoding.transparency" : True
               }


    def _do_paint_rgb24(self, img_data, x, y, width, height, rowstride, options):
        log("TrayBacking(%i)._do_paint_rgb24%s", self.wid, ("%s bytes" % len(img_data), x, y, width, height, rowstride, options))
        self.data = ["rgb24", width, height, rowstride, img_data[:]]
        return True

    def _do_paint_rgb32(self, img_data, x, y, width, height, rowstride, options):
        log("TrayBacking(%i)._do_paint_rgb32%s", self.wid, ("%s bytes" % len(img_data), x, y, width, height, rowstride, options))
        self.data = ["rgb32", width, height, rowstride, img_data[:]]
        return True
