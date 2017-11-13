#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.helper import dbus_to_native
from xpra.dbus.common import init_session_bus
from xpra.util import csv
import dbus.service

from xpra.log import Logger
log = Logger("dbus", "menu")


ACTIONS = "org.gtk.Actions"
MENUS = "org.gtk.Menus"


def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))

def di(v):
    return dbus.UInt32(v)
def ds(v):
    return dbus.String(v)

def busnamestr(o):
    try:
        return o._name._name
    except:
        return str(o)

def ordered_ints(*lists):
    """ merge all the lists and returned a sorted list with all the ints
        errors out if the values are not ints
    """
    import itertools
    return sorted(int(x) for x in set(itertools.chain(*lists)))


class Actions(dbus.service.Object):
    SUPPORTS_MULTIPLE_OBJECT_PATHS = True
    SUPPORTS_MULTIPLE_CONNECTIONS = True

    def __init__(self, name, path, session_bus, actions={}, default_callback=None):
        self.actions = actions
        self.default_callback = default_callback
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)
        self.log("%s", (name, path, session_bus, actions))

    def set_actions(self, actions):
        oldactions = self.actions
        self.actions = actions
        #build the change list for emitting the signal:
        # Four separate types of changes are possible,
        # and the 4 parameters of the change signal reflect these possibilities:
        # - as a list of removed actions
        # - a{sb} a list of actions that had their enabled flag changed
        # - a{sv} a list of actions that had their state changed
        # - a{s(bgav)} a list of new actions added in the same format as the return value of the DescribeAll method"""
        removed = dbus.Array(signature="s")
        enabled_changed = dbus.Array(signature="a{sb}")
        state_changed = dbus.Array(signature="a{sv}")
        added = dbus.Array(signature="a{s(bgav)}")
        all_actions = list(set(oldactions.keys() + actions.keys()))
        self.log(".set_actions(..) all actions=%s", csv(all_actions))
        for action in all_actions:
            if action not in actions:
                removed.append(ds(action))
                self.log(".set_actions(..) removed %s", action)
            elif action not in oldactions:
                action_def = actions[action]
                a = dbus.Struct(self._make_action(*action_def))
                v = dbus.Dictionary({ds(action) : a}, signature="s(bgav)")
                added.append(v)
                self.log(".set_actions(..) added %s=%s", action, action_def)
            else:   #maybe changed state?
                oldaction = oldactions.get(action, [False, None, None]) #default value should be redundant
                newaction = actions.get(action, [False, None, None])    #default value should be redundant
                if oldaction[0]!=newaction[0]:
                    v = dbus.Dictionary({ds(action) : dbus.Boolean(newaction[0])}, signature="sb")
                    enabled_changed.append(v)
                    self.log(".set_actions(..) enabled changed for %s from %s to %s", action, oldaction[0], newaction[0])
                if oldaction[2]!=newaction[2]:
                    v = dbus.Dictionary({ds(action) : newaction[2]}, signature="sv")
                    state_changed.append(v)
                    self.log(".set_actions(..) state changed for %s from %s to %s", action, oldaction[2], newaction[2])
        self.log(".set_actions(..) changes: %s", (removed, enabled_changed, state_changed, added))
        if removed or enabled_changed or state_changed or added:
            self.Changed(removed, enabled_changed, state_changed, added)

    @dbus.service.signal(ACTIONS, signature='asa{sb}a{sv}a{s(bgav)}')
    def Changed(self, removed, enabled_changed, state_changed, added):
        pass


    def log(self, fmt, *args):
        log("%s(%s:%s)"+fmt, ACTIONS,  busnamestr(self), self._object_path, *args)
    def warn(self, fmt, *args):
        log.warn("%s(%s:%s)"+fmt, ACTIONS,  busnamestr(self), self._object_path, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        raise dbus.exceptions.DBusException("this object does not have any properties")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, _interface_name):
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
        self.log(".List()=%s", csv(self.actions.keys()))
        return v


    def _make_action(self, enabled, ptype, state, callback=None):
        return dbus.Boolean(enabled), dbus.Signature(ptype), dbus.Array(state)

    @dbus.service.method(ACTIONS, in_signature="s", out_signature="(bgav)")
    def Describe(self, action):
        v = self.actions.get(action)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        r = self._make_action(*v)
        self.log(".Describe(%s)=%s", action, r)
        return r

    @dbus.service.method(ACTIONS, out_signature="a{s(bgav)}")
    def DescribeAll(self):
        #build the dbus struct list on demand (as it may change):
        d = {}
        for k,v in self.actions.items():
            #enabled, arg, state = v
            d[k] = dbus.Struct(self._make_action(*v))
        self.log(".DescribeAll()=%s", d)
        return dbus.Dictionary(d)

    @dbus.service.method(ACTIONS, in_signature="sava{sv}")
    def Activate(self, action, state, pdata):
        v = self.actions.get(action)
        self.log(".Activate%s action=%s", (action, state, pdata), v)
        if not v:
            raise dbus.exceptions.DBusException("unknown action '%s'" % action)
        if len(v)<4:
            cb = self.default_callback
        else:
            cb = v[3]
        if cb is None:
            self.warn(".Activate%s no callback for %s", (action, state, pdata), action)
            return
        paction = str(action)
        pstate = n(state)
        ppdata = n(pdata)
        self.log(".Activate%s calling %s%s", (action, state, pdata), cb, (self, paction, pstate, ppdata))
        try:
            cb(self, paction, pstate, ppdata)
        except Exception:
            log.error("Error: calling Activate callback %s", cb, exc_info=True)


    @dbus.service.method(ACTIONS, in_signature="sva{sv}")
    def SetState(self, s, v, a):
        return


class Menus(dbus.service.Object):
    SUPPORTS_MULTIPLE_OBJECT_PATHS = True
    SUPPORTS_MULTIPLE_CONNECTIONS = True

    def __init__(self, name, path, session_bus, menus={}):
        self.menus = menus
        self.subscribed = {}
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)
        self.log("%s", (name, path, session_bus, menus))

    def set_menus(self, menus):
        oldmenus = self.menus
        self.menus = menus
        #build the change list for emitting the signal:
        changed = []
        self.log(".set_menus(%s) old menus=%s", menus, oldmenus)
        groups_ids = ordered_ints(oldmenus.keys(), menus.keys())
        self.log(".set_menus(..) group_ids=%s", groups_ids)
        for group_id in groups_ids:
            oldgroup = oldmenus.get(group_id, {})
            group = menus.get(group_id, {})
            menu_ids = ordered_ints(oldgroup.keys(), group.keys())
            self.log(".set_menus(..) menu_ids(%s)=%s", group_id, menu_ids)
            for menu_id in menu_ids:
                oldmenu = oldgroup.get(menu_id, [])
                menu = group.get(menu_id, [])
                if menu==oldmenu:
                    continue
                self.log(".set_menus(..) found change at group=%i, menu_id=%i : from %s to %s", group_id, menu_id, oldmenu, menu)
                delcount = len(oldmenu)     #remove all
                insert = [self._make_menu_item(menu[i]) for i in range(len(menu))]
                changed.append(dbus.Struct(di(group_id), di(menu_id), di(0), di(delcount), dbus.Array(dbus.Array(insert))))
        self.log(".set_menus(..) changed: %s", changed)
        if changed:
            self.Changed(dbus.Array(changed))

    @dbus.service.signal(MENUS, signature='a(uuuuaa{sv})')
    def Changed(self, changes):
        pass


    def log(self, fmt, *args):
        log("%s(%s:%s)"+fmt, MENUS,  busnamestr(self), self._object_path, *args)
    def warn(self, fmt, *args):
        log.warn("%s(%s:%s)"+fmt, MENUS,  busnamestr(self), self._object_path, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ss', out_signature='v')
    def Get(self, interface_name, property_name):
        raise dbus.exceptions.DBusException("this object does not have any properties")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, _interface_name):
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
                self.warn(".Start(%s) invalid subscription group %i", ids, group)
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
        self.log(".Start(%s)=%s", ids, menus)
        return menus

    @dbus.service.method(MENUS, in_signature="au")
    def End(self, ids):
        for group in ids:
            c = self.subscribed.get(group, 0)
            if c > 0:
                self.subscribed[group] = c - 1


def get_actions_interface(bus_name, object_path):
    bus = init_session_bus()
    obj = bus.get_object(bus_name, object_path)
    log("%s:%s=%s", bus_name, object_path, obj)
    actions_iface = dbus.Interface(obj, ACTIONS)
    log("%s(%s)=%s", ACTIONS, obj, actions_iface)
    return actions_iface

def query_actions(bus_name, object_path, actions_cb=None, error_cb=None):
    actions_iface = get_actions_interface(bus_name, object_path)
    def actions_changed(*args):
        log("actions_changed%s", args)
        if actions_cb:
            actions_iface.DescribeAll(reply_handler=describe_all_actions, error_handler=describe_all_error)
    def actions_list(*args):
        log("actions_list%s", args)
    def actions_error(*args):
        log("actions_error%s", args)
        if error_cb:
            error_cb(args)
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
        if actions_cb:
            actions_cb(actions)
    def describe_all_error(*args):
        log("describe_all_error%s", args)
        if error_cb:
            error_cb(args)
    actions_iface.DescribeAll(reply_handler=describe_all_actions, error_handler=describe_all_error)
    return actions_iface


def get_menu_interface(bus_name, object_path):
    bus = init_session_bus()
    obj = bus.get_object(bus_name, object_path)
    log("%s:%s=%s", bus_name, object_path, obj)
    menu_iface = dbus.Interface(obj, MENUS)
    log("%s(%s)=%s", MENUS, obj, menu_iface)
    return menu_iface

def query_menu(bus_name, object_path, menu_cb=None, menu_err=None):
    menu_iface = get_menu_interface(bus_name, object_path)
    def menus_changed(*args):
        log("menus_changed%s", args)
        if menu_cb:
            menu_iface.End([0])
            menu_iface.Start([0], reply_handler=menus_start_cb, error_handler=menus_start_err)
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
                accel = d.get("accel")
                if accel:
                    menu["accel"] = n(accel)
                if menu:
                    dmenus.append(menu)
            menus.setdefault(ni(sgroup), {})[ni(menuno)] = dmenus
        log("menus=%s", menus)
        if menu_cb:
            menu_cb(menus)
    def menus_start_err(*args):
        log("menus_start_err%s", args)
        if menu_err:
            menu_err(args)
    menu_iface.Start([0], reply_handler=menus_start_cb, error_handler=menus_start_err)
    return menu_iface
