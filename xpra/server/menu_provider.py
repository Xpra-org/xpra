# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from threading import Lock
from typing import Dict, Any, Optional, List, Callable

from gi.repository import GLib  # @UnresolvedImport

from xpra.common import DEFAULT_XDG_DATA_DIRS
from xpra.os_util import (
    OSX, POSIX, WIN32,
    osexpand,
    )
from xpra.util import envint, envbool
from xpra.make_thread import start_thread
from xpra.server.background_worker import add_work_item
from xpra.log import Logger

log = Logger("menu")

MENU_WATCHER = envbool("XPRA_MENU_WATCHER", True)
MENU_RELOAD_DELAY = envint("XPRA_MENU_RELOAD_DELAY", 5)
EXPORT_XDG_MENU_DATA = envbool("XPRA_EXPORT_XDG_MENU_DATA", True)


def noicondata(menu_data:Dict) -> Dict:
    newdata = {}
    for k,v in menu_data.items():
        if k in ("IconData", b"IconData"):
            continue
        if isinstance(v, dict):
            newdata[k] = noicondata(v)
        else:
            newdata[k] = v
    return newdata


singleton = None
def get_menu_provider():
    global singleton
    if singleton is None:
        singleton = MenuProvider()
    return singleton


class MenuProvider:
    __slots__ = (
        "watch_manager", "watch_notifier", "xdg_menu_reload_timer",
        "on_reload", "menu_data", "desktop_sessions", "load_lock",
        )

    def __init__(self):
        self.watch_manager = None
        self.watch_notifier = None
        self.xdg_menu_reload_timer = 0
        self.on_reload : List[Callable] = []
        self.menu_data : Optional[Dict[str,Any]] = None
        self.desktop_sessions : Optional[Dict[str,Any]] = None
        self.load_lock = Lock()

    def setup(self) -> None:
        if OSX or not EXPORT_XDG_MENU_DATA:
            return
        if MENU_WATCHER:
            self.setup_menu_watcher()
        self.load_menu_data()

    def cleanup(self) -> None:
        self.on_reload = []
        self.cancel_xdg_menu_reload()
        self.cancel_pynotify_watch()


    def setup_menu_watcher(self) -> None:
        try:
            self.do_setup_menu_watcher()
        except Exception as e:
            log("threaded_setup()", exc_info=True)
            log.error("Error setting up menu watcher:")
            log.estr(e)

    def do_setup_menu_watcher(self) -> None:
        if self.watch_manager or OSX or WIN32:
            #already setup
            return
        try:
            # pylint: disable=import-outside-toplevel
            import pyinotify
        except ImportError as e:
            log("setup_menu_watcher() cannot import pyinotify", exc_info=True)
            log.warn("Warning: cannot watch for application menu changes without pyinotify:")
            log.warn(" %s", e)
            return
        self.watch_manager = pyinotify.WatchManager()
        def menu_data_updated(create, pathname):
            log("menu_data_updated(%s, %s)", create, pathname)
            self.schedule_xdg_menu_reload()
        class EventHandler(pyinotify.ProcessEvent):
            def process_IN_CREATE(self, event):
                menu_data_updated(True, event.pathname)
            def process_IN_DELETE(self, event):
                menu_data_updated(False, event.pathname)
        mask = pyinotify.IN_DELETE | pyinotify.IN_CREATE  #@UndefinedVariable pylint: disable=no-member
        handler = EventHandler()
        self.watch_notifier = pyinotify.ThreadedNotifier(self.watch_manager, handler)
        self.watch_notifier.daemon = True
        data_dirs = os.environ.get("XDG_DATA_DIRS", DEFAULT_XDG_DATA_DIRS).split(":")
        watched = []
        for data_dir in data_dirs:
            menu_dir = os.path.join(osexpand(data_dir), "applications")
            if not os.path.exists(menu_dir) or menu_dir in watched:
                continue
            wdd = self.watch_manager.add_watch(menu_dir, mask)
            watched.append(menu_dir)
            log("watch_notifier=%s, watch=%s", self.watch_notifier, wdd)
        self.watch_notifier.start()
        if watched:
            log.info("watching for applications menu changes in:")
            for wd in watched:
                log.info(" '%s'", wd)

    def cancel_pynotify_watch(self) -> None:
        wn = self.watch_notifier
        if wn:
            self.watch_notifier = None
            wn.stop()
        wm = self.watch_manager
        if wm:
            self.watch_manager = None
            try:
                wm.close()
            except OSError:
                log("error closing watch manager %s", wm, exc_info=True)


    def load_menu_data(self, force_reload:bool=False) -> None:
        #start loading in a thread,
        #as this may take a while and
        #so server startup can complete:
        def load() -> None:
            try:
                self.get_menu_data(force_reload)
                self.get_desktop_sessions()
            except ImportError as e:
                log.warn("Warning: cannot load menu data")
                log.warn(f" {e}")
            except Exception:
                log.error("Error loading menu data", exc_info=True)
            finally:
                self.clear_cache()
        start_thread(load, "load-menu-data", True)

    def get_menu_data(self, force_reload=False, remove_icons=False, wait=True) -> Dict[str,Any]:
        log("get_menu_data%s", (force_reload, remove_icons, wait))
        if not EXPORT_XDG_MENU_DATA:
            return {}
        if OSX:
            return {}
        menu_data = self.menu_data
        if self.load_lock.acquire(wait):  # pylint: disable=consider-using-with
            menu_data = self.menu_data
            try:
                if self.menu_data is None or force_reload:
                    from xpra.platform.menu_helper import load_menu  #pylint: disable=import-outside-toplevel
                    self.menu_data = load_menu()
                    add_work_item(self.got_menu_data)
            finally:
                self.load_lock.release()
        if remove_icons and self.menu_data:
            menu_data = noicondata(self.menu_data)
        return menu_data or {}

    def got_menu_data(self) -> bool:
        log("got_menu_data(..) on_reload=%s", self.on_reload)
        for cb in self.on_reload:
            cb(self.menu_data)
        return False

    def clear_cache(self) -> None:
        from xpra.platform.menu_helper import clear_cache  #pylint: disable=import-outside-toplevel
        log("%s()", clear_cache)
        clear_cache()

    def cancel_xdg_menu_reload(self) -> None:
        xmrt = self.xdg_menu_reload_timer
        if xmrt:
            self.xdg_menu_reload_timer = 0
            GLib.source_remove(xmrt)

    def schedule_xdg_menu_reload(self) -> None:
        self.cancel_xdg_menu_reload()
        self.xdg_menu_reload_timer = GLib.timeout_add(MENU_RELOAD_DELAY*1000, self.xdg_menu_reload)

    def xdg_menu_reload(self) -> bool:
        self.xdg_menu_reload_timer = 0
        log("xdg_menu_reload()")
        self.load_menu_data(True)
        return False


    def get_menu_icon(self, category_name, app_name):
        xdg_menu = self.get_menu_data()
        if not xdg_menu:
            return None, None
        category = xdg_menu.get(category_name)
        if not category:
            log("get_menu_icon: invalid menu category '%s'", category_name)
            return None, None
        if app_name is None:
            return category.get("IconType"), category.get("IconData")
        entries = category.get("Entries")
        if not entries:
            log("get_menu_icon: no entries for category '%s'", category_name)
            return None, None
        app = entries.get(app_name)
        if not app:
            log("get_menu_icon: no matching application for '%s' in category '%s'",
                app_name, category_name)
            return None, None
        return app.get("IconType"), app.get("IconData")


    def get_desktop_sessions(self, force_reload:bool=False, remove_icons:bool=False) -> Dict[str,Any]:
        if not POSIX or OSX:
            return {}
        if force_reload or self.desktop_sessions is None:
            from xpra.platform.posix.menu_helper import load_desktop_sessions  #pylint: disable=import-outside-toplevel
            self.desktop_sessions = load_desktop_sessions()
        desktop_sessions = self.desktop_sessions
        if remove_icons:
            desktop_sessions = noicondata(desktop_sessions)
        return desktop_sessions

    def get_desktop_menu_icon(self, sessionname:str):
        desktop_sessions = self.get_desktop_sessions(False) or {}
        de = desktop_sessions.get(sessionname, {})
        return de.get("IconType"), de.get("IconData")


    def get_info(self, _proto) -> Dict[str,Any]:
        return self.get_menu_data(remove_icons=True)
