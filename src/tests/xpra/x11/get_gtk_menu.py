#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.x11.gtk2.gdk_display_source import display    #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_get
from xpra.util import AdHocStruct
from xpra.dbus.helper import DBusHelper

#beware: this import has side-effects:
import dbus.glib
assert dbus.glib

from xpra.dbus.common import loop_init


def main(args):
    wid = sys.argv[1]
    w = AdHocStruct()
    if wid.startswith("0x"):
        w.xid = int(wid[2:], 16)
    else:
        w.xid = int(wid)
    def pget(key, etype, ignore_errors=True):
        return prop_get(w, key, etype, ignore_errors=False, raise_xerrors=False)
    #ie: /org/gnome/baobab/menus/appmenu
    menu_path = pget("_GTK_APP_MENU_OBJECT_PATH", "utf8")
    #ie: /org/gnome/baobab/window/1
    window_path = pget("_GTK_WINDOW_OBJECT_PATH", "utf8")
    #ie: /org/gnome/baobab
    app_path = pget("_GTK_APPLICATION_OBJECT_PATH", "utf8")
    #ie: :1.745
    bus_name = pget("_GTK_UNIQUE_BUS_NAME", "utf8")
    #ie: org.gnome.baobab
    app_id = pget("_GTK_APPLICATION_ID", "utf8")
    props = {
            "app-menu-path"     : menu_path,
            "window-path"       : window_path,
            "application-path"  : app_path,
            "bus-name"          : bus_name,
            "application-id"    : app_id,
            }
    print("gtk menu properties for window %s on display %s: %s" % (wid, display.get_name(), props))
    if not (menu_path and window_path and app_path and bus_name and app_id):
        print("some properties are missing - cannot continue")
        return

    loop_init()
    import gobject
    loop = gobject.MainLoop()
    dbus_helper = DBusHelper()
    def n(*args):
        return dbus_helper.dbus_to_native(*args)
    def ni(*args):
        return int(n(*args))

    bus = dbus_helper.get_session_bus()
    window = bus.get_object(bus_name, window_path)
    print("window=%s" % window)

    #actions:
    interface = "org.gtk.Actions"
    iface = dbus.Interface(window, interface)
    print("iface(%s)=%s" % (interface, iface))
    def actions_changed(*args):
        print("actions_changed%s" % str(args))
    iface.connect_to_signal("Changed", actions_changed)

    def list_cb(*args):
        values = dbus_helper.dbus_to_native(args[0])
        print("list_cb: values=%s" % str(values))
    def list_err(*args):
        print("list_err%s" % str(args))
    dbus_helper.call_function(bus_name, window_path, interface, "List", [], list_cb, list_err)
    dbus_helper.call_function(bus_name, app_path, interface, "List", [], list_cb, list_err)

    def describe_actions_cb(*args):
        print("describe_actions_cb:")
        values = dbus_helper.dbus_to_native(args[0])
        #print("describe_cb: values=%s" % str(values))
        actions = {}
        for k,v in values.items():
            #enabled, parameter type, state
            mdef = [bool(n(v[0])), n(v[1]), [n(x) for x in v[2]]]
            #print(" %s=%s" % (k, mdef))
            actions[k] = mdef
        print("actions=%s" % actions)
    def describe_actions_err(*args):
        print("describe_actions_err%s" % str(args))
    dbus_helper.call_function(bus_name, window_path, interface, "DescribeAll", [], describe_actions_cb, describe_actions_err)
    dbus_helper.call_function(bus_name, app_path, interface, "DescribeAll", [], describe_actions_cb, describe_actions_err)

    #app menu:
    interface = "org.gtk.Menus"
    iface = dbus.Interface(window, interface)
    print("iface(%s)=%s" % (interface, iface))
    def menus_changed(*args):
        print("menus_changed%s" % str(args))
    iface.connect_to_signal("Changed", menus_changed)

    def menus_start_cb(*args):
        #print("menus_start_cb args=%s" % str(args))
        #print("menus_start_cb args[0]=%s" % str(args[0]))
        values = n(args[0])
        #print("menus_start_cb values=%s" % str(values))
        menus = {}
        for sgroup, menuno, items in values:
            print(" %s: %s - %s" % (sgroup, menuno, n(items)))
            dmenus = []
            for d in items:
                menu = {}
                section = d.get(":section")
                submenu = d.get(":submenu")
                if section:
                    #subscription, menu
                    menu[":section"] = ni(section[0]), ni(section[1])
                elif section or submenu:
                    #subscription, menu
                    menu[":submenu"] = ni(section[0]), ni(section[1])
                else:
                    #action?
                    for k in ("action", "label"):
                        if k in d:
                            menu[k] = n(d[k])
                    if menu:
                        target = d.get("target")
                        if target:
                            menu["target"] = [n(target[x]) for x in range(len(target))] 
                            #print("target=%s (len=%s)" % (target, len(target)))
                if menu:
                    dmenus.append(menu)
            menus.setdefault(ni(sgroup), {})[ni(menuno)] = dmenus
        print("menus=%s" % menus)
        #values = dbus_helper.dbus_to_native(args[0])
    def menus_start_err(*args):
        print("menus_start_err%s" % str(args))
    dbus_helper.call_function(bus_name, menu_path, interface, "Start", [[0]], menus_start_cb, menus_start_err)

    loop.run()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
