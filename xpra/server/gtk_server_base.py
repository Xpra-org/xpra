# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#pylint: disable=wrong-import-position

import sys
from time import monotonic
from typing import Dict, Tuple, Any, Callable, Optional

import gi
gi.require_version('Gdk', '3.0')  # @UndefinedVariable
gi.require_version('Gtk', '3.0')  # @UndefinedVariable
from gi.repository import GLib, Gdk, Gtk  #pylint: disable=no-name-in-module

from xpra.util import flatten_dict, envbool
from xpra.version_util import dict_version_trim
from xpra.common import FULL_INFO
from xpra.net.common import PacketType
from xpra.gtk_common.gobject_compat import register_os_signals
from xpra.server import server_features
from xpra.server.server_base import ServerBase
from xpra.gtk_common.gtk_util import get_gtk_version_info, get_root_size
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
        self.cursor_suspended : bool = False
        self.ui_watcher = None
        self.keymap_changing_timer : int = 0
        self.cursor_sizes = self.get_cursor_sizes()
        super().__init__()

    def watch_keymap_changes(self) -> None:
        ### Set up keymap change notification:
        display = Gdk.Display.get_default()
        if not display:
            log.warn("Warning: no default Gdk Display!")
            return
        keymap = Gdk.Keymap.get_for_display(display)
        #this event can fire many times in succession
        #throttle how many times we call self._keys_changed()
        def keys_changed(*_args):
            if self.keymap_changing_timer:
                return
            def do_keys_changed():
                self._keys_changed()
                self.keymap_changing_timer = 0
            self.keymap_changing_timer = self.timeout_add(500, do_keys_changed)
        keymap.connect("keys-changed", keys_changed)

    def stop_keymap_timer(self) -> None:
        kct = self.keymap_changing_timer
        if kct:
            self.keymap_changing_timer = 0
            self.source_remove(kct)

    def install_signal_handlers(self, callback:Callable) -> None:
        sstr = self.get_server_mode()+" server"
        register_os_signals(callback, sstr)
        from xpra.gtk_common.gobject_compat import register_SIGUSR_signals  # pylint: disable=import-outside-toplevel
        register_SIGUSR_signals(sstr)

    def do_quit(self) -> None:
        log("do_quit: calling Gtk.main_quit")
        Gtk.main_quit()
        log("do_quit: Gtk.main_quit done")
        #from now on, we can't rely on the main loop:
        from xpra.os_util import register_SIGUSR_signals    # pylint: disable=import-outside-toplevel
        register_SIGUSR_signals()

    def late_cleanup(self) -> None:
        log("GTKServerBase.late_cleanup()")
        self.stop_keymap_timer()
        super().late_cleanup()
        self.stop_ui_watcher()
        self.close_gtk_display()

    def stop_ui_watcher(self) -> None:
        uiw = self.ui_watcher
        log("stop_ui_watcher() ui watcher=%s", uiw)
        if uiw:
            self.ui_watcher = None
            uiw.stop()

    def close_gtk_display(self) -> None:
        # Close our display(s) first, so the server dying won't kill us.
        # (if gtk has been loaded)
        gdk_mod = sys.modules.get("gi.repository.Gdk")
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


    def do_run(self) -> None:
        if UI_THREAD_WATCHER:
            from xpra.platform.ui_thread_watcher import get_UI_watcher  # pylint: disable=import-outside-toplevel
            self.ui_watcher = get_UI_watcher(GLib.timeout_add, GLib.source_remove)
            self.ui_watcher.start()
        if server_features.windows:
            display = Gdk.Display.get_default()
            if display:
                #n = display.get_n_screens()
                #assert n==1, "unsupported number of screens: %i" % n
                screen = display.get_default_screen()
                screen.connect("size-changed", self._screen_size_changed)
                screen.connect("monitors-changed", self._monitors_changed)
        log("do_run() calling %s", Gtk.main)
        Gtk.main()
        log("do_run() end of gtk.main()")


    def make_hello(self, source) -> Dict[str,Any]:
        capabilities = super().make_hello(source)
        if "display" in source.wants:
            display = Gdk.Display.get_default()
            if display:
                max_size = tuple(display.get_maximal_cursor_size())
                capabilities.update({
                    "display"               : display.get_name(),
                    "cursor.default_size"   : display.get_default_cursor_size(),
                    "cursor.max_size"       : max_size,
                    })
        if "versions" in source.wants and FULL_INFO>=2:
            capabilities.update(flatten_dict(get_gtk_version_info()))
        return capabilities

    def get_ui_info(self, proto, *args) -> Dict[str,Any]:
        info = super().get_ui_info(proto, *args)
        display = Gdk.Display.get_default()
        if display:
            info.setdefault("server", {}).update({
                "display"             : display.get_name(),
                "root_window_size"    : self.get_root_window_size(),
                })
            info.setdefault("cursor", {}).update(self.get_ui_cursor_info())
        return info


    def suspend_cursor(self, proto) -> None:
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

    def restore_cursor(self, proto) -> None:
        #see suspend_cursor
        if not self.cursor_suspended:
            return
        self.cursor_suspended = False
        ss = self.get_server_source(proto)
        if ss:
            ss.send_cursor()


    def get_cursor_sizes(self) -> Tuple[int,int]:
        display = Gdk.Display.get_default()
        if not display:
            return (0, 0)
        return int(display.get_default_cursor_size()), display.get_maximal_cursor_size()


    def send_initial_cursors(self, ss, _sharing=False) -> None:
        #cursors: get sizes and send:
        cursorlog("send_initial_cursors() cursor_sizes=%s", self.cursor_sizes)
        ss.send_cursor()

    def get_ui_cursor_info(self) -> Dict[str,Any]:
        #(from UI thread)
        #now cursor size info:
        display = Gdk.Display.get_default()
        if not display:
            return {}
        pos = display.get_default_screen().get_root_window().get_pointer()[-3:-1]
        cinfo = {"position" : pos}
        for prop, size in {
            "default" : display.get_default_cursor_size(),
            "max"     : tuple(display.get_maximal_cursor_size()),
            }.items():
            if size is None:
                continue
            cinfo[f"{prop}_size"] = size
        return cinfo

    def do_get_info(self, proto, *args) -> Dict[str,Any]:
        start = monotonic()
        info = super().do_get_info(proto, *args)
        vi = dict_version_trim(get_gtk_version_info())
        vi["type"] = "Python/gtk"
        info.setdefault("server", {}).update(vi)
        log("GTKServerBase.do_get_info took %ims", (monotonic()-start)*1000)
        return info

    def get_root_window_size(self) -> Tuple[int,int]:
        return get_root_size(None)

    def get_max_screen_size(self) -> Tuple[int,int]:
        return get_root_size(None)

    def configure_best_screen_size(self)-> Tuple[int,int]:
        return self.get_root_window_size()

    def calculate_workarea(self, maxw:int, maxh:int) -> None:
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
        """ overridden by seamless servers """

    def set_desktop_geometry(self, width:int, height:int) -> None:
        """ overridden by X11 seamless and desktop servers """


    def _move_pointer(self, device_id:int, wid:int, pos, props=None) -> None:
        x, y = pos
        display = Gdk.Display.get_default()
        display.warp_pointer(display.get_default_screen(), x, y)

    def do_process_button_action(self, *args):
        raise NotImplementedError


    def _process_map_window(self, proto, packet : PacketType) -> None:
        log.info("_process_map_window(%s, %s)", proto, packet)

    def _process_unmap_window(self, proto, packet : PacketType) -> None:
        log.info("_process_unmap_window(%s, %s)", proto, packet)

    def _process_close_window(self, proto, packet : PacketType) -> None:
        log.info("_process_close_window(%s, %s)", proto, packet)

    def _process_configure_window(self, proto, packet : PacketType) -> None:
        log.info("_process_configure_window(%s, %s)", proto, packet)


    def get_notification_icon(self, icon_string:str) -> Optional[Tuple[str,int,int,bytes]]:
        try:
            from xpra.notifications.common import get_notification_icon
        except ImportError:
            return None
        return get_notification_icon(icon_string)
