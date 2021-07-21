# -*- coding: utf-8 -*-
# This file is part of Xpra.
# Copyright (C) 2010-2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
from threading import Lock

from gi.repository import GLib

from xpra.common import DEFAULT_XDG_DATA_DIRS
from xpra.os_util import (
    OSX, WIN32, POSIX,
    osexpand,
    )
from xpra.util import envint, envbool
from xpra.make_thread import start_thread
from xpra.server.background_worker import add_work_item
from xpra.log import Logger

log = Logger("menu")

MENU_RELOAD_DELAY = envint("XPRA_MENU_RELOAD_DELAY", 5)
EXPORT_XDG_MENU_DATA = envbool("XPRA_EXPORT_XDG_MENU_DATA", True)


def noicondata(menu_data):
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

    def __init__(self):
        self.watch_manager = None
        self.watch_notifier = None
        self.xdg_menu_reload_timer = None
        self.on_reload = []
        self.menu_data = None
        self.desktop_sessions = None
        self.load_lock = Lock()

    def setup(self):
        if not POSIX or OSX or not EXPORT_XDG_MENU_DATA:
            return
        self.setup_menu_watcher()
        self.load_menu_data()

    def cleanup(self):
        self.on_reload = []
        self.cancel_xdg_menu_reload()
        self.cancel_pynotify_watch()


    def setup_menu_watcher(self):
        try:
            self.do_setup_menu_watcher()
        except Exception as e:
            log("threaded_setup()", exc_info=True)
            log.error("Error setting up menu watcher:")
            log.error(" %s", e)
        from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
        #start loading in a thread,
        #so server startup can complete:
        start_thread(load_xdg_menu_data, "load-xdg-menu-data", True)

    def do_setup_menu_watcher(self):
        if self.watch_manager:
            #already setup
            return
        try:
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
        self.watch_notifier.setDaemon(True)
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

    def cancel_pynotify_watch(self):
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


    def load_menu_data(self, force_reload=False):
        #start loading in a thread,
        #as this may take a while and
        #so server startup can complete:
        def load():
            self.get_menu_data(force_reload)
            self.get_desktop_sessions()
        start_thread(load, "load-menu-data", True)

    def get_menu_data(self, force_reload=False, remove_icons=False, wait=True):
        log("get_menu_data%s", (force_reload, remove_icons, wait))
        if not EXPORT_XDG_MENU_DATA:
            return None
        if OSX:
            return None
        menu_data = self.menu_data
        if self.load_lock.acquire(wait):
            try:
                if not self.menu_data or force_reload:
                    if POSIX:
                        from xpra.platform.xposix.xdg_helper import load_xdg_menu_data
                        menu_data = load_xdg_menu_data()
                    elif WIN32:
                        from xpra.platform.win32.menu_helper import load_menu
                        menu_data = load_menu()
                    else:
                        log.error("Error: unsupported platform!")
                        return None
                    self.menu_data = menu_data
                    add_work_item(self.got_menu_data)
            finally:
                self.load_lock.release()
        if remove_icons and self.menu_data:
            menu_data = noicondata(self.menu_data)
        return menu_data

    def got_menu_data(self):
        log("got_menu_data(..) on_reload=%s", self.on_reload)
        for cb in self.on_reload:
            cb(self.menu_data)
        return False


    def cancel_xdg_menu_reload(self):
        xmrt = self.xdg_menu_reload_timer
        if xmrt:
            self.xdg_menu_reload_timer = None
            GLib.source_remove(xmrt)

    def schedule_xdg_menu_reload(self):
        self.cancel_xdg_menu_reload()
        self.xdg_menu_reload_timer = GLib.timeout_add(MENU_RELOAD_DELAY*1000, self.xdg_menu_reload)

    def xdg_menu_reload(self):
        self.xdg_menu_reload_timer = None
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


    def get_desktop_sessions(self, force_reload=False, remove_icons=False):
        if not POSIX or OSX:
            return None
        if force_reload or self.desktop_sessions is None:
            from xpra.platform.xposix.xdg_helper import load_desktop_sessions
            self.desktop_sessions = load_desktop_sessions()
        desktop_sessions = self.desktop_sessions
        if remove_icons:
            desktop_sessions = noicondata(desktop_sessions)
        return desktop_sessions

    def get_desktop_menu_icon(self, sessionname):
        desktop_sessions = self.get_desktop_sessions(False) or {}
        de = desktop_sessions.get(sessionname, {})
        return de.get("IconType"), de.get("IconData")


    def get_info(self, _proto) -> dict:
        return self.get_menu_data(remove_icons=True)
