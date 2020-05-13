# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2020 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import sys
import os.path
import gi
gi.require_version('Gdk', '3.0')
gi.require_version('Gtk', '3.0')
gi.require_version('Pango', '1.0')
from gi.repository import GLib, Gdk, Gtk

from xpra.util import flatten_dict, envbool
from xpra.os_util import monotonic_time, WIN32
from xpra.gtk_common.gobject_compat import register_os_signals, register_SIGUSR_signals
from xpra.gtk_common.quit import (
    gtk_main_quit_really,
    gtk_main_quit_on_fatal_exceptions_enable,
    gtk_main_quit_on_fatal_exceptions_disable,
    )
from xpra.server import server_features
from xpra.server.server_base import ServerBase
from xpra.gtk_common.gtk_util import (
    get_gtk_version_info, get_root_size,
    )
from xpra.log import Logger

UI_THREAD_WATCHER = envbool("XPRA_UI_THREAD_WATCHER")

log = Logger("server", "gtk")
screenlog = Logger("server", "screen")
cursorlog = Logger("server", "cursor")
notifylog = Logger("notify")


class GTKServerBase(ServerBase):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See X11ServerBase, XpraServer and XpraX11ShadowServer
    """

    def __init__(self):
        log("GTKServerBase.__init__()")
        self.idle_add = GLib.idle_add
        self.timeout_add = GLib.timeout_add
        self.source_remove = GLib.source_remove
        self.cursor_suspended = False
        self.ui_watcher = None
        ServerBase.__init__(self)

    def watch_keymap_changes(self):
        ### Set up keymap change notification:
        display = Gdk.Display.get_default()
        keymap = Gdk.Keymap.get_for_display(display)
        keymap.connect("keys-changed", self._keys_changed)

    def install_signal_handlers(self, callback):
        sstr = "%s Server" % self.get_server_mode()
        register_os_signals(callback, sstr)
        register_SIGUSR_signals(sstr)

    def signal_quit(self, signum, frame=None):
        gtk_main_quit_on_fatal_exceptions_disable()
        super().signal_quit(signum, frame)

    def do_quit(self):
        log("do_quit: calling gtk_main_quit_really")
        gtk_main_quit_on_fatal_exceptions_disable()
        gtk_main_quit_really()
        log("do_quit: gtk_main_quit_really done")
        #from now on, we can't rely on the main loop:
        from xpra.os_util import register_SIGUSR_signals
        register_SIGUSR_signals()

    def do_cleanup(self):
        ServerBase.do_cleanup(self)
        self.close_gtk_display()
        uiw = self.ui_watcher
        if uiw:
            uiw.stop()

    def close_gtk_display(self):
        # Close our display(s) first, so the server dying won't kill us.
        # (if gtk has been loaded)
        gdk_mod = sys.modules.get("gtk.gdk") or sys.modules.get("gi.repository.Gdk")
        #bug 2328: python3 shadow server segfault on Ubuntu 16.04
        #also crashes on Ubuntu 20.04
        close = envbool("XPRA_CLOSE_GTK_DISPLAY", False)
        log("close_gtk_display() close=%s, gdk_mod=%s",
            close, gdk_mod)
        if close and gdk_mod:
            displays = Gdk.DisplayManager.get().list_displays()
            log("close_gtk_display() displays=%s", displays)
            for d in displays:
                log("close_gtk_display() closing %s", d)
                d.close()


    def do_run(self):
        if UI_THREAD_WATCHER:
            from xpra.platform.ui_thread_watcher import get_UI_watcher
            self.ui_watcher = get_UI_watcher(GLib.timeout_add, GLib.source_remove)
            self.ui_watcher.start()
        if server_features.windows:
            display = Gdk.Display.get_default()
            i=0
            while i<display.get_n_screens():
                screen = display.get_screen(i)
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)
                i += 1
        gtk_main_quit_on_fatal_exceptions_enable()
        log("do_run() calling %s", Gtk.main)
        Gtk.main()
        log("do_run() end of gtk.main()")


    def make_hello(self, source):
        capabilities = super().make_hello(source)
        if source.wants_display:
            display = Gdk.Display.get_default()
            max_size = tuple(display.get_maximal_cursor_size())
            capabilities.update({
                "display"               : display.get_name(),
                "cursor.default_size"   : display.get_default_cursor_size(),
                "cursor.max_size"       : max_size,
                })
        if source.wants_versions:
            capabilities.update(flatten_dict(get_gtk_version_info()))
        return capabilities

    def get_ui_info(self, proto, *args):
        info = super().get_ui_info(proto, *args)
        info.setdefault("server", {}).update({
                                              "display"             : Gdk.Display.get_default().get_name(),
                                              "root_window_size"    : self.get_root_window_size(),
                                              })
        info.setdefault("cursor", {}).update(self.get_ui_cursor_info())
        return info


    def suspend_cursor(self, proto):
        #this is called by shadow and desktop servers
        #when we're receiving pointer events but the pointer
        #is no longer over the active window area,
        #so we have to tell the client to switch back to the default cursor
        if self.cursor_suspended:
            return
        self.cursor_suspended = True
        ss = self.get_server_source(proto)
        if ss:
            ss.cancel_cursor_timer()
            ss.send_empty_cursor()

    def restore_cursor(self, proto):
        #see suspend_cursor
        if not self.cursor_suspended:
            return
        self.cursor_suspended = False
        ss = self.get_server_source(proto)
        if ss:
            ss.send_cursor()


    def send_initial_cursors(self, ss, _sharing=False):
        #cursors: get sizes and send:
        display = Gdk.Display.get_default()
        self.cursor_sizes = int(display.get_default_cursor_size()), display.get_maximal_cursor_size()
        cursorlog("send_initial_cursors() cursor_sizes=%s", self.cursor_sizes)
        ss.send_cursor()

    def get_ui_cursor_info(self) -> dict:
        #(from UI thread)
        #now cursor size info:
        display = Gdk.Display.get_default()
        pos = display.get_default_screen().get_root_window().get_pointer()[-3:-1]
        cinfo = {"position" : pos}
        for prop, size in {
            "default" : display.get_default_cursor_size(),
            "max"     : tuple(display.get_maximal_cursor_size()),
            }.items():
            if size is None:
                continue
            cinfo["%s_size" % prop] = size
        return cinfo

    def do_get_info(self, proto, *args):
        start = monotonic_time()
        info = super().do_get_info(proto, *args)
        vi = get_gtk_version_info()
        vi["type"] = "Python/gtk"
        info.setdefault("server", {}).update(vi)
        log("GTKServerBase.do_get_info took %ims", (monotonic_time()-start)*1000)
        return info

    def get_root_window_size(self):
        return get_root_size()

    def get_max_screen_size(self):
        max_w, max_h = get_root_size()
        return max_w, max_h

    def configure_best_screen_size(self):
        root_w, root_h = get_root_size()
        return root_w, root_h

    def calculate_workarea(self, maxw, maxh):
        screenlog("calculate_workarea(%s, %s)", maxw, maxh)
        workarea = Gdk.Rectangle()
        workarea.width = maxw
        workarea.height = maxh
        for ss in self._server_sources.values():
            screen_sizes = ss.screen_sizes
            screenlog("calculate_workarea() screen_sizes(%s)=%s", ss, screen_sizes)
            if not screen_sizes:
                continue
            for display in screen_sizes:
                #avoid error with old/broken clients:
                if not display or not isinstance(display, (list, tuple)):
                    continue
                #display: [':0.0', 2560, 1600, 677, 423, [['DFP2', 0, 0, 2560, 1600, 646, 406]], 0, 0, 2560, 1574]
                if len(display)>=10:
                    work_x, work_y, work_w, work_h = display[6:10]
                    display_workarea = Gdk.Rectangle()
                    display_workarea.x = work_x
                    display_workarea.y = work_y
                    display_workarea.width = work_w
                    display_workarea.height = work_h
                    screenlog("calculate_workarea() found %s for display %s", display_workarea, display[0])
                    success, workarea = workarea.intersect(display_workarea)
                    if not success:
                        log.warn("Warning: failed to calculate workarea")
                        log.warn(" as intersection of %s and %s", (maxw, maxh), (work_x, work_y, work_w, work_h))
        #sanity checks:
        screenlog("calculate_workarea(%s, %s) workarea=%s", maxw, maxh, workarea)
        if workarea.width==0 or workarea.height==0 or workarea.width>=32768-8192 or workarea.height>=32768-8192:
            screenlog.warn("Warning: failed to calculate a common workarea")
            screenlog.warn(" using the full display area: %ix%i", maxw, maxh)
            workarea = Gdk.Rectangle()
            workarea.width = maxw
            workarea.height = maxh
        self.set_workarea(workarea)

    def set_workarea(self, workarea):
        pass

    def set_desktop_geometry(self, width, height):
        pass

    def set_dpi(self, xdpi, ydpi):
        pass


    def _move_pointer(self, _wid, pos, *_args):
        x, y = pos
        display = Gdk.Display.get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def do_process_button_action(self, *args):
        pass


    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)


    def get_notification_icon(self, icon_string):
        #the string may be:
        # * a path which we will load using pillow
        # * a name we lookup in the current them
        if not icon_string:
            return ()
        img = None
        from PIL import Image
        if os.path.isabs(icon_string):
            if os.path.exists(icon_string) and os.path.isfile(icon_string):
                img = Image.open(icon_string)
                w, h = img.size
        else:
            #try to find it in the theme:
            theme = Gtk.IconTheme.get_default()
            if theme:
                try:
                    icon = theme.load_icon(icon_string, Gtk.IconSize.BUTTON, 0)
                except Exception as e:
                    notifylog("failed to load icon '%s' from default theme: %s", icon_string, e)
                else:
                    data = icon.get_pixels()
                    w = icon.get_width()
                    h = icon.get_height()
                    rowstride = icon.get_rowstride()
                    mode = "RGB"
                    if icon.get_has_alpha():
                        mode = "RGBA"
                    img = Image.frombytes(mode, (w, h), data, "raw", mode, rowstride)
        if img:
            if w>256 or h>256:
                img = img.resize((256, 256), Image.ANTIALIAS)
                w = h = 256
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, "PNG")
            cpixels = buf.getvalue()
            buf.close()
            return "png", w, h, cpixels
        return ()
