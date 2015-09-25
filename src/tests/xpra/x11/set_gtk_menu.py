#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import sys
from xpra.x11.gtk2.gdk_display_source import display    #@UnresolvedImport
from xpra.x11.gtk_x11.prop import prop_set
from xpra.dbus.helper import DBusHelper, dbus_to_native

#beware: this import has side-effects:
import dbus.glib
assert dbus.glib
import dbus.service
import gtk

from xpra.dbus.common import loop_init


class Actions(dbus.service.Object):
    SUPPORTS_MULTIPLE_OBJECT_PATHS = True
 
    def __init__(self, name, path, session_bus, actions={}):
        self.actions = actions
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)

    def set_actions(self, actions):
        self.actions = actions
        #TODO: diff and emit the "Change" signal


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        raise dbus.exceptions.DBusException("this object does not have any properties")
 
    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, interface_name):
        return []

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        self.PropertiesChanged(interface_name, { property_name: new_value }, [])

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass


    @dbus.service.method('org.gtk.Actions', out_signature="as")
    def List(self):
        print("List()")
        return dbus.Array(dbus.String(x) for x in self.actions.keys())


    def _make_action(self, enabled, ptype, state):
        return dbus.Boolean(enabled), dbus.Signature(ptype), dbus.Array(state)
 
    @dbus.service.method('org.gtk.Actions', in_signature="s", out_signature="(bgav)")
    def Describe(self, action):
        v = self.actions.get(action)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        r = self._make_action(*v[:3])
        print("Describe(%s)=%s" % (action, r))
        return r

    @dbus.service.method('org.gtk.Actions', out_signature="a{s(bgav)}")
    def DescribeAll(self):
        #build the dbus struct list on demand (as it may change):
        d = {}
        for k,v in self.actions.items():
            #enabled, arg, state = v
            d[k] = dbus.Struct(self._make_action(*v[:3]))
        print("DescribeAll()=%s" % d)
        return dbus.Dictionary(d)

    #async_callbacks=("ok_cb", "err_cb")
    @dbus.service.method('org.gtk.Actions', in_signature="sava{sv}")
    def Activate(self, action, state, pdata):
        v = self.actions.get(action)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        if len(v)<4:
            print("no callback for %s" % action)
        cb = v[3]
        pstate = dbus_to_native(state)
        ppdata = dbus_to_native(pdata)
        print("Activate(%s, %s, %s) calling %s%s" % (action, state, pdata, cb, (pstate, ppdata)))
        cb(action, pstate, ppdata)


    @dbus.service.method('org.gtk.Actions', in_signature="sva{sv}")
    def SetState(self, s, v, a):
        return

    @dbus.service.signal('org.gtk.Actions', signature='s')
    def Changed(self, arg):
        return []


class Menus(dbus.service.Object):
 
    def __init__(self, name, path, session_bus, menus={}):
        self.menus = menus
        self.subscribed = {}
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)
        self.set_menus(menus)

    def set_menus(self, menus):
        self.menus = menus


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        raise dbus.exceptions.DBusException("this object does not have any properties")
 
    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface_name):
        return []

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        raise dbus.exceptions.DBusException("this object does not have any properties")

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass


    def _make_menu_item(self, d):
        def s(v):
            try:
                return dbus.String(v.decode())
            except:
                return dbus.String(str(v))
        section = d.get(":section")
        if section:
            #{':section': (0, 1)}
            return dbus.Dictionary({s(":section") : (dbus.UInt32(section[0]), dbus.UInt32(section[1]))})
        submenu = d.get(":submenu")
        if submenu:
            #{':submenu': (0, 1)}
            return dbus.Dictionary({s(":submenu") : (dbus.UInt32(section[0]), dbus.UInt32(section[1]))})
        action = d.get("action")
        if not action:
            print("unknown menu item type: %s" % d)
            return None
        menu_item = {s("action") : s(action)}
        if "label" in d:
            menu_item[s("label")] = s(d["label"])
        target = d.get("target")
        if target:
            menu_item["target"] = dbus.Struct(target)
        return dbus.Dictionary(menu_item)

    @dbus.service.method('org.gtk.Menus', in_signature="au", out_signature="a(uuaa{sv})")
    def Start(self, ids):
        #print("Start(%s)" % str(ids))
        menus = []
        for group in ids:
            group_menus = self.menus.get(group)
            if group_menus is None:
                print("Warning: invalid subscription group %i", group)
                continue
            self.subscribed[group] = self.subscribed.get(group, 0)+1
            for n, items in group_menus.items():
                menu_items = []
                for i in items:
                    try:
                        menu_item = self._make_menu_item(i)
                    except:
                        continue
                    #print("make_menu_item(%s)=%s" % (i, menu_item))
                    if menu_item:
                        menu_items.append(menu_item)
                if menu_items:
                    menus.append((group, dbus.UInt32(n), menu_items))
        print("Start(%s)=%s" % (ids, menus))
        return menus
 
    @dbus.service.method('org.gtk.Menus', in_signature="au")
    def End(self, ids):
        for group in ids:
            c = self.subscribed.get(group, 0)
            if c > 0:
                self.subscribed[group] = c - 1
 
    @dbus.service.signal('org.gtk.Menus', signature='a(uuuuaa{sv})')
    def Changed(self, arg):
        return



def main(args):
    window = gtk.Window(gtk.WINDOW_TOPLEVEL)
    window.set_size_request(200, 200)
    window.connect("delete_event", gtk.mainquit)
    window.realize()
    w = window.get_window()

    dbus_helper = DBusHelper()
    loop_init()
    session_bus = dbus_helper.get_session_bus()

    app_id = u"org.xpra.Terminal"
    app_path = u"/org/xpra/Terminal"
    menu_path = u"%s/menus/appmenu" % app_path
    window_path = u"%s/window/1" % app_path
    bus_name = session_bus.get_unique_name().decode()

    def action_cb(*args):
        print("action_cb%s" % str(args))
    window_actions={'reset'         : [True, 'b', [], action_cb],
                    'fullscreen'    : [True, '', [0], action_cb],
                    'about'         : [True, '', [], action_cb],
                    'preferences'   : [True, '', [], action_cb],
                    'switch-tab'    : [True, 'i', [], action_cb],
                    'detach-tab'    : [True, '', []],
                    'save-contents' : [True, '', []],
                    'edit-profile'  : [True, 's', []],
                    'zoom'          : [True, 'i', []],
                    'move-tab'      : [True, 'i', []],
                    'new-terminal'  : [True, '(ss)', []],
                    'select-all'    : [True, '', []],
                    'new-profile'   : [True, '', []],
                    'show-menubar'  : [True, '', [1]],
                    'close'         : [True, 's', []],
                    'copy'          : [True, '', []],
                    'paste'         : [True, 's', []],
                    'find'          : [True, 's', []],
                    'help'          : [True, '', []]}
    menuactions_service = Actions(app_id, window_path, session_bus, window_actions)
    app_actions = {
                    'quit'          : [True, '', []],
                    'about'         : [True, '', []],
                    'activate-tab'  : [True, 's', []],
                    'preferences'   : [True, '', []],
                    'help'          : [True, '', []]
                  }
    appactions_service = Actions(app_id, app_path, session_bus, app_actions)
    menus = {0:
             {0: [{':section': (0, 1)}, {':section': (0, 2)}, {':section': (0, 3)}],
              1: [{'action': 'win.new-terminal', 'label': '_New Terminal', 'target': ['default', 'default']}],
              2: [{'action': 'app.preferences', 'label': '_Preferences'}],
              3: [{'action': 'app.help', 'label': '_Help'},
                  {'action': 'app.about', 'label': '_About'},
                  {'action': 'app.quit', 'label': '_Quit'}
                  ]
              }
             }
    menus_service = Menus(app_id, menu_path, session_bus, menus)

    def pset(key, etype, value, ignore_errors=True):
        return prop_set(w, key, etype, value)
    pset("_GTK_APP_MENU_OBJECT_PATH", "utf8", menu_path)
    pset("_GTK_WINDOW_OBJECT_PATH", "utf8", window_path)
    pset("_GTK_APPLICATION_OBJECT_PATH", "utf8", app_path)
    pset("_GTK_UNIQUE_BUS_NAME", "utf8", bus_name)
    pset("_GTK_APPLICATION_ID", "utf8", app_id)
    print("gtk menu properties for window %#x on display %s" % (w.xid, display.get_name()))

    window.show()
    gtk.main()
    del menuactions_service, appactions_service, menus_service


if __name__ == '__main__':
    sys.exit(main(sys.argv))
