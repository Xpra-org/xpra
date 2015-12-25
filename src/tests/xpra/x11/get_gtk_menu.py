#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.log import Logger
log = Logger("dbus")


def get_menuaction_props(w):
    from xpra.x11.gtk_x11.prop import prop_get
    def pget(key, etype):
        return prop_get(w, key, etype, ignore_errors=True, raise_xerrors=True)
    props = {}
    for k,x11name in {
            "application-id"    : "_GTK_APPLICATION_ID",            #ie: org.gnome.baobab
            "bus-name"          : "_GTK_UNIQUE_BUS_NAME",           #ie: :1.745
            "application-path"  : "_GTK_APPLICATION_OBJECT_PATH",   #ie: /org/gnome/baobab
            "app-menu-path"     : "_GTK_APP_MENU_OBJECT_PATH",      #ie: /org/gnome/baobab/menus/appmenu
            "window-path"       : "_GTK_WINDOW_OBJECT_PATH",        #ie: /org/gnome/baobab/window/1
            }.items():
        v = pget(x11name, "utf8")
        if v:
            props[k] = v
    return props


def query_menuactions(app_id, bus_name,
                      app_path,     app_actions_cb,     app_actions_err,
                      window_path,  window_actions_cb,  window_actions_err,
                      menu_path,    menu_cb,            menu_err):
    if not (menu_path and window_path and app_path and bus_name and app_id):
        log.error("Error: some properties are missing - cannot continue")
        return
    from xpra.dbus.gtk_menuactions import query_actions, query_menu
    aa = query_actions(bus_name, app_path, app_actions_cb, app_actions_err)
    wa = query_actions(bus_name, window_path, window_actions_cb, window_actions_err)
    am = query_menu(bus_name, menu_path, menu_cb, menu_err)
    return (aa, wa, am)

def dump_menuactions(display, xid):
    from xpra.util import AdHocStruct
    w = AdHocStruct()
    w.xid = xid
    try:
        props = get_menuaction_props(w)
    except Exception as e:
        log.error("Error: failed to get menus / actions for window %s:", w)
        log.error(" %s", e)
        return None

    log("gtk menu properties for window %#x on display %s: %s", xid, display.get_name(), props)
    app_id      = props.get("application-id")
    bus_name    = props.get("bus-name")
    app_path    = props.get("application-path")
    menu_path   = props.get("app-menu-path")
    window_path = props.get("window-path")
    if not (app_id and bus_name and app_path and menu_path and window_path):
        log.error("Error: some properties are missing - cannot continue")
        return

    return query_menuactions(app_id, bus_name,
                             app_path,      None, None,
                             window_path,   None, None,
                             menu_path,     None, None)


def main(args):
    from xpra.platform import program_context
    from xpra.log import enable_color
    with program_context("GTK-Menu Info"):
        enable_color()
        if "-q" in sys.argv:
            sys.argv.remove("-q")
        elif "--quiet" in sys.argv:
            sys.argv.remove("--quiet")
        else:
            log.enable_debug()
            from xpra.dbus.gtk_menuactions import log as gtkmalog
            gtkmalog.enable_debug()
        try:
            from xpra.x11.gtk2.gdk_display_source import display    #@UnresolvedImport
            wid = sys.argv[1]
            if wid.startswith("0x"):
                xid = int(wid[2:], 16)
            else:
                xid = int(wid)
        except Exception as e:
            log.error("Error: invalid window id: %s", e)
            log.error("usage:")
            log.error(" %s WINDOWID", sys.argv[0])
        else:
            #beware: this import has side-effects:
            import dbus.glib
            assert dbus.glib
            from xpra.dbus.common import loop_init
            loop_init()
            import gobject
            loop = gobject.MainLoop()
            v = dump_menuactions(display, xid)
            loop.run()
            del v


if __name__ == '__main__':
    sys.exit(main(sys.argv))
