# coding=utf8
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import gtk.gdk
import gobject
gobject.threads_init()

from xpra.log import Logger
log = Logger()

from xpra.gtk_common.quit import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)
from xpra.server.server_base import ServerBase
from xpra.gtk_common.gtk_util import add_gtk_version_info
from xpra.net.protocol import set_scheduler
set_scheduler(gobject)


class GTKServerBase(ServerBase):
    """
        This is the base class for servers.
        It provides all the generic functions but is not tied
        to a specific backend (X11 or otherwise).
        See X11ServerBase, XpraServer and XpraX11ShadowServer
    """

    def __init__(self):
        log("ServerBase.__init__()")
        self.idle_add = gobject.idle_add
        self.timeout_add = gobject.timeout_add
        self.source_remove = gobject.source_remove
        ServerBase.__init__(self)
        ### Misc. state:
        self._settings = {}
        self._xsettings_manager = None

    def watch_keymap_changes(self):
        ### Set up keymap change notification:
        gtk.gdk.keymap_get_default().connect("keys-changed", self._keys_changed)

    def do_quit(self):
        gtk_main_quit_really()

    def do_run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        log("calling gtk.main")
        gtk.main()
        log("xpra end of gtk.main().")

    def add_listen_socket(self, sock):
        sock.listen(5)
        gobject.io_add_watch(sock, gobject.IO_IN, self._new_connection, sock)

    def make_hello(self):
        capabilities = ServerBase.make_hello(self)
        capabilities["display"] = gtk.gdk.display_get_default().get_name()
        capabilities["cursor.default_size"] = gtk.gdk.display_get_default().get_default_cursor_size()
        add_gtk_version_info(capabilities, gtk)
        return capabilities

    def do_get_info(self, proto, server_sources, window_ids):
        info = ServerBase.do_get_info(self, proto, server_sources, window_ids)
        add_gtk_version_info(info, gtk)
        info["server_type"] = "Python/gtk-x11"
        info["root_window_size"] = gtk.gdk.get_default_root_window().get_size()
        info["randr"] = self.randr
        return info

    def get_root_window_size(self):
        return gtk.gdk.get_default_root_window().get_size()

    def get_max_screen_size(self):
        max_w, max_h = gtk.gdk.get_default_root_window().get_size()
        return max_w, max_h

    def set_best_screen_size(self):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        return root_w, root_h

    def calculate_workarea(self):
        root_w, root_h = gtk.gdk.get_default_root_window().get_size()
        workarea = gtk.gdk.Rectangle(0, 0, root_w, root_h)
        for ss in self._server_sources.values():
            screen_sizes = ss.screen_sizes
            log("screen_sizes(%s)=%s", ss, screen_sizes)
            if not screen_sizes:
                continue
            for display in screen_sizes:
                #avoid error with old/broken clients:
                if not display or type(display) not in (list, tuple):
                    continue
                #display: [':0.0', 2560, 1600, 677, 423, [['DFP2', 0, 0, 2560, 1600, 646, 406]], 0, 0, 2560, 1574]
                if len(display)>10:
                    work_x, work_y, work_w, work_h = display[6:10]
                    display_workarea = gtk.gdk.Rectangle(work_x, work_y, work_w, work_h)
                    log("found workarea % for display %s", display_workarea, display[0])
                    workarea = workarea.intersect(display_workarea)
        #sanity checks:
        if workarea.width==0 or workarea.height==0:
            log.warn("failed to calculate a common workarea - using the full display area")
            workarea = gtk.gdk.Rectangle(0, 0, root_w, root_h)
        self.set_workarea(workarea)

    def set_workarea(self, workarea):
        pass


    def _move_pointer(self, pos):
        x, y = pos
        display = gtk.gdk.display_get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def _process_mouse_common(self, proto, wid, pointer, modifiers):
        pass

    def _process_button_action(self, proto, packet):
        pass


    def _process_map_window(self, proto, packet):
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet):
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet):
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet):
        log.info("_process_configure_window(%s, %s)", proto, packet)

    def _process_move_window(self, proto, packet):
        log.info("_process_move_window(%s, %s)", proto, packet)

    def _process_resize_window(self, proto, packet):
        log.info("_process_resize_window(%s, %s)", proto, packet)
