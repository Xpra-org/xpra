#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.helper import dbus_to_native
from xpra.dbus.common import init_session_bus
import dbus.service

from xpra.log import Logger
log = Logger("dbus")

ACTIONS = "org.gtk.Actions"
MENUS = "org.gtk.Menus"


def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))


class Actions(dbus.service.Object):
    SUPPORTS_MULTIPLE_OBJECT_PATHS = True
 
    def __init__(self, name, path, session_bus, actions={}):
        self.actions = actions
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)

    def set_actions(self, actions):
        self.actions = actions
        #TODO: diff and emit the "Change" signal


    def log(self, fmt, *args):
        log("%s(%s:%s)"+fmt, ACTIONS, self._name, self._object_path, *args)


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


    @dbus.service.method(ACTIONS, out_signature="as")
    def List(self):
        v = dbus.Array(dbus.String(x) for x in self.actions.keys())
        self.log(".List()=%s", v)
        return v


    def _make_action(self, enabled, ptype, state):
        return dbus.Boolean(enabled), dbus.Signature(ptype), dbus.Array(state)
 
    @dbus.service.method(ACTIONS, in_signature="s", out_signature="(bgav)")
    def Describe(self, action):
        v = self.actions.get(action)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        r = self._make_action(*v[:3])
        self.log(".Describe(%s)=%s", action, r)
        return r

    @dbus.service.method(ACTIONS, out_signature="a{s(bgav)}")
    def DescribeAll(self):
        #build the dbus struct list on demand (as it may change):
        d = {}
        for k,v in self.actions.items():
            #enabled, arg, state = v
            d[k] = dbus.Struct(self._make_action(*v[:3]))
        self.log(".DescribeAll()=%s", d)
        return dbus.Dictionary(d)

    #async_callbacks=("ok_cb", "err_cb")
    @dbus.service.method(ACTIONS, in_signature="sava{sv}")
    def Activate(self, action, state, pdata):
        v = self.actions.get(action)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        if len(v)<4:
            self.log.warn(".Activate%s no callback for %s", (action, state, pdata), action)
            return
        cb = v[3]
        pstate = n(state)
        ppdata = n(pdata)
        self.log("Activate(%s, %s, %s) calling %s%s", action, state, pdata, cb, (pstate, ppdata))
        cb(action, pstate, ppdata)


    @dbus.service.method(ACTIONS, in_signature="sva{sv}")
    def SetState(self, s, v, a):
        return

    @dbus.service.signal(ACTIONS, signature='s')
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
        #TODO: diff and emit the "Change" signal


    def log(self, fmt, *args):
        log("%s(%s:%s)"+fmt, MENUS, self._name, self._object_path, *args)


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

    @dbus.service.method(MENUS, in_signature="au", out_signature="a(uuaa{sv})")
    def Start(self, ids):
        menus = []
        for group in ids:
            group_menus = self.menus.get(group)
            if group_menus is None:
                self.log.warn(".Start(%s) invalid subscription group %i", ids, group)
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
        self.log("Start(%s)=%s", ids, menus)
        return menus
 
    @dbus.service.method(MENUS, in_signature="au")
    def End(self, ids):
        for group in ids:
            c = self.subscribed.get(group, 0)
            if c > 0:
                self.subscribed[group] = c - 1
 
    @dbus.service.signal(MENUS, signature='a(uuuuaa{sv})')
    def Changed(self, arg):
        return


def query_actions(bus_name, object_path, actions_cb=None, error_cb=None):
    bus = init_session_bus()
    obj = bus.get_object(bus_name, object_path)
    log("%s:%s=%s", bus_name, object_path, obj)
    actions_iface = dbus.Interface(obj, ACTIONS)
    log("%s(%s)=%s", ACTIONS, obj, actions_iface)
    def actions_changed(*args):
        log("actions_changed%s", args)
        if actions_cb:
            actions_cb()
    def actions_list(*args):
        log("actions_list%s", args)
    def actions_error(*args):
        log("actions_error%s", args)
        if error_cb:
            error_cb()
    actions_iface.List(reply_handler=actions_list, error_handler=actions_error)
    def describe_all_actions(values):
        log("describe_all_actions(%s)", values)
        values = n(values)
        actions = {}
        for k,v in values.items():
            #enabled, parameter type, state
            mdef = [bool(n(v[0])), n(v[1]), [n(x) for x in v[2]]]
            log(" %s=%s", k, mdef)
            actions[k] = mdef
        log("actions=%s", actions)
    def describe_all_error(*args):
        log("describe_all_error%s", args)
        if error_cb:
            error_cb()
    actions_iface.DescribeAll(reply_handler=describe_all_actions, error_handler=describe_all_error)
    return actions_iface


def query_menu(bus_name, object_path, menu_cb=None, menu_err=None):
    bus = init_session_bus()
    obj = bus.get_object(bus_name, object_path)
    menu_iface = dbus.Interface(obj, MENUS)
    log("%s(%s)=%s", MENUS, obj, menu_iface)
    def menus_changed(*args):
        log("menus_changed%s", args)
        if menu_cb:
            menu_cb()
    menu_iface.connect_to_signal("Changed", menus_changed)
    def menus_start_cb(values):
        menus = {}
        for sgroup, menuno, items in n(values):
            log(" %s: %s - %s", sgroup, menuno, n(items))
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
                if menu:
                    dmenus.append(menu)
            menus.setdefault(ni(sgroup), {})[ni(menuno)] = dmenus
        log("menus=%s", menus)
    def menus_start_err(*args):
        log("menus_start_err%s", args)
        if menu_err:
            menu_err()
    menu_iface.Start([0], reply_handler=menus_start_cb, error_handler=menus_start_err)
    return menu_iface
