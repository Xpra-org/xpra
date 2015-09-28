# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
menulog = Logger("menu")


def has_gtk_menu_support(root_window):
    #figure out if we can handle the "global menu" stuff:
    try:
        from xpra.dbus.helper import DBusHelper
        assert DBusHelper
    except Exception as e:
        menulog("has_menu_support() no dbus: %s", e)
        return False
    try:
        from xpra.x11.gtk_x11.prop import prop_get
    except Exception as e:
        menulog("has_menu_support() no X11 bindings: %s", e)
        return False
    v = prop_get(root_window, "_NET_SUPPORTED", ["atom"], ignore_errors=True, raise_xerrors=False)
    if not v:
        menulog("has_menu_support() _NET_SUPPORTED is empty!?")
        return False
    show_window_menu = "_GTK_SHOW_WINDOW_MENU" in v
    menulog("has_menu_support() _GTK_SHOW_WINDOW_MENU in _NET_SUPPORTED: %s", show_window_menu)
    return show_window_menu
