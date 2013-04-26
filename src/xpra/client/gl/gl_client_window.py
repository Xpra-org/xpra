# This file is part of Xpra.
# Copyright (C) 2012 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2012, 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from wimpiggy.log import Logger
log = Logger()

from xpra.client.gtk2.client_window import ClientWindow
from xpra.client.gl.gl_window_backing import GLPixmapBacking, debug


class GLClientWindow(ClientWindow):

    gl_pixmap_backing_class = GLPixmapBacking

    def __init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay):
        debug("GLClientWindow(..)")
        ClientWindow.__init__(self, client, group_leader, wid, x, y, w, h, metadata, override_redirect, client_properties, auto_refresh_delay)
        self.set_reallocate_redraws(True)
        self.add(self._backing.glarea)

    def is_GL(self):
        return True

    def spinner(self, ok):
        if not self._backing.paint_screen or not self._backing.glarea or not self.can_have_spinner():
            return
        w, h = self.get_size()
        if ok:
            self._backing.render_image(0, 0, w, h)
            self.queue_draw(self._backing.glarea, 0, 0, w, h)
        else:
            import gtk.gdk
            window = self.gdk_window(self._backing.glarea)
            context = window.cairo_create()
            self.paint_spinner(context, gtk.gdk.Rectangle(0, 0, w, h))

    def do_expose_event(self, event):
        debug("GL do_expose_event(%s)", event)

    def do_configure_event(self, event):
        debug("GL do_configure_event(%s)", event)
        ClientWindow.do_configure_event(self, event)
        self._backing.paint_screen = True

    def destroy(self):
        self._backing.paint_screen = False
        ClientWindow.destroy(self)

    def new_backing(self, w, h):
        debug("GL new_backing(%s, %s)", w, h)
        w = max(2, w)
        h = max(2, h)
        lock = None
        if self._backing:
            lock = self._backing._video_decoder_lock
        try:
            if lock:
                lock.acquire()
            if self._backing is None:
                self._backing = self.gl_pixmap_backing_class(self._id, w, h, self._client.supports_mmap, self._client.mmap)
            self._backing.init(w, h)
        finally:
            if lock:
                lock.release()
