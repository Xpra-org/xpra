# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.client.gtk_client_base import GTKXpraClient
import gobject
import gtk
from gtk import gdk

from xpra.scripts.config import ENCODINGS
from xpra.client.gtk2.client_window import ClientWindow
from xpra.gtk_common.cursor_names import cursor_names
from wimpiggy.log import Logger
log = Logger()


class XpraClient(GTKXpraClient):

    WINDOW_TOPLEVEL = gdk.WINDOW_TOPLEVEL
    INPUT_ONLY = gdk.INPUT_ONLY

    def __init__(self, conn, opts):
        GTKXpraClient.__init__(self, conn, opts)
        try:
            from xpra.client.gl.gl_client_window import GLClientWindow
            self.GLClientWindowClass = GLClientWindow
        except:
            self.GLClientWindowClass = None

    def client_type(self):
        return "Python/Gtk2"

    def make_hello(self, challenge_response=None):
        capabilities = GTKXpraClient.make_hello(self, challenge_response)
        capabilities["encoding.supports_delta"] = [x for x in ("png", "rgb24") if x in ENCODINGS]
        return capabilities

    def process_ui_capabilities(self, capabilities):
        GTKXpraClient.process_ui_capabilities(self, capabilities)
        if self.server_randr:
            display = gdk.display_get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                i += 1

    def _screen_size_changed(self, *args):
        root_w, root_h = self.get_root_size()
        log.debug("sending updated screen size to server: %sx%s", root_w, root_h)
        self.send("desktop_size", root_w, root_h, self.get_screen_sizes())
        #update the max packet size (may have gone up):
        self.set_max_packet_size()

    def get_screen_sizes(self):
        display = gdk.display_get_default()
        i=0
        screen_sizes = []
        while i<display.get_n_screens():
            screen = display.get_screen(i)
            j = 0
            monitors = []
            while j<screen.get_n_monitors():
                geom = screen.get_monitor_geometry(j)
                plug_name = ""
                if hasattr(screen, "get_monitor_plug_name"):
                    plug_name = screen.get_monitor_plug_name(j) or ""
                wmm = -1
                if hasattr(screen, "get_monitor_width_mm"):
                    wmm = screen.get_monitor_width_mm(j)
                hmm = -1
                if hasattr(screen, "get_monitor_height_mm"):
                    hmm = screen.get_monitor_height_mm(j)
                monitor = plug_name, geom.x, geom.y, geom.width, geom.height, wmm, hmm
                monitors.append(monitor)
                j += 1
            root = screen.get_root_window()
            work_x, work_y = 0, 0
            work_width, work_height = screen.get_width(), screen.get_height()
            if not sys.platform.startswith("win"):
                try:
                    p = gtk.gdk.atom_intern('_NET_WORKAREA')
                    work_x, work_y, work_width, work_height = root.property_get(p)[2][:4]
                except:
                    pass
            item = (screen.make_display_name(), screen.get_width(), screen.get_height(),
                        screen.get_width_mm(), screen.get_height_mm(),
                        monitors,
                        work_x, work_y, work_width, work_height)
            screen_sizes.append(item)
            i += 1
        log("get_screen_sizes()=%s", screen_sizes)
        return screen_sizes


    def get_root_size(self):
        return gdk.get_default_root_window().get_size()

    def set_windows_cursor(self, gtkwindows, new_cursor):
        cursor = None
        if len(new_cursor)>0:
            cursor = None
            if len(new_cursor)>=9 and cursor_names:
                cursor_name = new_cursor[8]
                if cursor_name:
                    gdk_cursor = cursor_names.get(cursor_name.upper())
                    if gdk_cursor is not None:
                        try:
                            from wimpiggy.error import trap
                            log("setting new cursor: %s=%s", cursor_name, gdk_cursor)
                            cursor = trap.call_synced(gdk.Cursor, gdk_cursor)
                        except:
                            pass
            if cursor is None:
                w, h, xhot, yhot, serial, pixels = new_cursor[2:8]
                log("new cursor at %s,%s with serial=%s, dimensions: %sx%s, len(pixels)=%s" % (xhot,yhot, serial, w,h, len(pixels)))
                pixbuf = gdk.pixbuf_new_from_data(pixels, gdk.COLORSPACE_RGB, True, 8, w, h, w * 4)
                x = max(0, min(xhot, w-1))
                y = max(0, min(yhot, h-1))
                size = gdk.display_get_default().get_default_cursor_size()
                if size>0 and (size<w or size<h):
                    ratio = float(max(w,h))/size
                    pixbuf = pixbuf.scale_simple(int(w/ratio), int(h/ratio), gdk.INTERP_BILINEAR)
                    x = int(x/ratio)
                    y = int(y/ratio)
                cursor = gdk.Cursor(gdk.display_get_default(), pixbuf, x, y)
        for gtkwindow in gtkwindows:
            if gtk.gtk_version>=(2,14):
                gdkwin = gtkwindow.get_window()
            else:
                gdkwin = gtkwindow.window
            #trays don't have a gdk window
            if gdkwin:
                gdkwin.set_cursor(cursor)


    def init_opengl(self, enable_opengl):
        #enable_opengl can be True, False or None (auto-detect)
        self.opengl_enabled = False
        self.GLClientWindowClass = None
        self.opengl_props = {}
        from xpra.scripts.config import OpenGL_safety_check
        check = OpenGL_safety_check()
        if check:
            if enable_opengl is True:
                log.warn("OpenGL enabled despite: %s", check)
            else:
                self.opengl_props["info"] = "disabled: %s" % check
                log.warn("OpenGL disabled: %s", check)
                return
        if enable_opengl is False:
            self.opengl_props["info"] = "disabled by configuration"
            return
        self.opengl_props["info"] = ""
        try:
            try:
                from xpra.client import gl     #@UnusedImport
                from xpra.client.gl.gl_check import check_support
                w, h = self.get_root_size()
                min_texture_size = max(w, h)
                self.opengl_props = check_support(min_texture_size, force_enable=(enable_opengl is True))

                from xpra.client.gl.gl_client_window import GLClientWindow
                self.GLClientWindowClass = GLClientWindow
                self.opengl_enabled = True
            except ImportError, e:
                log.info("OpenGL support not enabled: %s", e)
                self.opengl_props["info"] = str(e)
        except Exception, e:
            log.error("Error loading OpenGL support: %s", e, exc_info=True)
            self.opengl_props["info"] = str(e)

    def group_leader_for_pid(self, pid, wid):
        if sys.platform.startswith("win") or pid<=0:
            #avoid ugly "not implemented" warning on win32
            return None
        group_leader = self._pid_to_group_leader.get(pid)
        if not group_leader:
            #create one:
            title = "%s group leader for %s" % (self.session_name or "Xpra", pid)
            group_leader = gdk.Window(None, 1, 1, self.WINDOW_TOPLEVEL, 0, self.INPUT_ONLY, title)
            self._pid_to_group_leader[pid] = group_leader
            log("new hidden group leader window %s for pid=%s", group_leader, pid)
        self._group_leader_wids.setdefault(group_leader, []).append(wid)
        return group_leader

    def get_client_window_class(self, metadata):
        if self.GLClientWindowClass is None or not self.opengl_enabled:
            return ClientWindow
        if self.mmap_enabled or self.encoding not in ("x264", "vpx"):
            #plain gtk2
            return ClientWindow
        #only enable GL for normal windows:
        window_types = metadata.get("window-type", ())
        if "_NET_WM_WINDOW_TYPE_NORMAL" not in window_types:
            return ClientWindow
        return self.GLClientWindowClass


gobject.type_register(XpraClient)
