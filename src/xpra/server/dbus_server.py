#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.helper import dbus_to_native
from xpra.dbus.common import init_session_bus
from xpra.util import parse_scaling_value, from0to100, AdHocStruct
import dbus.service

from xpra.log import Logger, add_debug_category, remove_debug_category, disable_debug_for, enable_debug_for
log = Logger("dbus", "server")

INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"


def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))
def ns(*args):
    return str(n(*args))


def stoms(v):
    return int(v*1000.0)


class DBUS_Server(dbus.service.Object):

    def __init__(self, server=None, pathextra=""):
        self.server = server
        session_bus = init_session_bus()
        bus_name = dbus.service.BusName(INTERFACE, session_bus)
        path = PATH
        if pathextra:
            path += "/"+pathextra
        dbus.service.Object.__init__(self, bus_name, path)
        self.log("(%s)", server)
        self._properties = {"idle-timeout"          : ("idle_timeout",          ni),
                            "server-idle-timeout"   : ("server_idle_timeout",   ni),
                            "name"                  : ("session_name",          ns),
                            }

    def cleanup(self):
        self.remove_from_connection()


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='s', out_signature='v')
    def Get(self, property_name):
        conv = self._properties.get(property_name)
        if conv is None:
            raise dbus.exceptions.DBusException("invalid property")
        server_property_name, _ = conv
        v = getattr(self.server, server_property_name)
        self.log(".Get(%s)=%s", property_name, v)
        return v

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='', out_signature='a{sv}')
    def GetAll(self, interface_name):
        if interface_name==INTERFACE:
            v = dict((x, self.Get(x)) for x in self._properties.keys())
        else:
            v = {}
        self.log(".GetAll(%s)=%s", interface_name, v)
        return v

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature='ssv')
    def Set(self, interface_name, property_name, new_value):
        self.log(".Set(%s, %s, %s)", interface_name, property_name, new_value)
        conv = self._properties.get(property_name)
        if conv is None:
            raise dbus.exceptions.DBusException("invalid property")
        server_property_name, validator = conv
        assert hasattr(self.server, server_property_name)
        setattr(self.server, server_property_name, validator(new_value))

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature='sa{sv}as')
    def PropertiesChanged(self, interface_name, changed_properties, invalidated_properties):
        pass


    @dbus.service.method(INTERFACE, in_signature='i')
    def Focus(self, wid):
        self.server.control_command_focus(wid)

    @dbus.service.method(INTERFACE, in_signature='')
    def Suspend(self):
        self.server.control_command_suspend()

    @dbus.service.method(INTERFACE, in_signature='')
    def Resume(self):
        self.server.control_command_resume()

    @dbus.service.method(INTERFACE, in_signature='')
    def Ungrab(self):
        self.server.control_command_resume()


    @dbus.service.method(INTERFACE, in_signature='s')
    def Start(self, command):
        self.server.do_control_command_start(True, command)

    @dbus.service.method(INTERFACE, in_signature='s')
    def StartChild(self, command):
        self.server.do_control_command_start(False, command)


    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyPress(self, keycode):
        self.server.control_command_key(keycode, press=True)

    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyRelease(self, keycode):
        self.server.control_command_key(keycode, press=False)

    @dbus.service.method(INTERFACE)
    def ClearKeysPressed(self):
        self.server._clear_keys_pressed()

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetKeyboardRepeat(self, repeat_delay, repeat_interval):
        self.server.set_keyboard_repeat(repeat_delay, repeat_interval)


    @dbus.service.method(INTERFACE, in_signature='iii')
    def MovePointer(self, wid, x, y):
        self.server._move_pointer(wid, (x, y))

    @dbus.service.method(INTERFACE, in_signature='iibiias')
    def MouseClick(self, wid, button, pressed, x, y, modifiers):
        packet = [wid, button, pressed, (x, y), modifiers]
        self.server._process_button_action(None, packet)


    @dbus.service.method(INTERFACE, in_signature='iiii')
    def SetWorkarea(self, x, y, w, h):
        workarea = AdHocStruct()
        workarea.x, workarea.y, workarea.width, workarea.height = x, y, w, h
        self.server.set_workarea(workarea)


    @dbus.service.method(INTERFACE, in_signature='', out_signature='v')
    def ListWindows(self):
        d = {}
        for wid, window in self.server._id_to_window.items():
            try:
                d[wid] = window.get_property("title")
            except:
                d[wid] = str(window)
        return d


    @dbus.service.method(INTERFACE, in_signature='ii')
    def MoveWindowToWorkspace(self, wid, workspace):
        self.server.control_command_workspace(wid, workspace)

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowScaling(self, wid, scaling):
        s = parse_scaling_value(scaling)
        self.server.control_command_scaling(s, wid)

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetWindowScalingControl(self, wid, scaling_control):
        sc = from0to100(scaling_control)
        self.server.control_command_scaling_control(sc, wid)

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowEncoding(self, wid, encoding):
        self.server.control_command_encoding(encoding, wid)

    @dbus.service.method(INTERFACE, in_signature='i')
    def RefreshWindow(self, wid):
        self.server.control_command_refresh(wid)


    @dbus.service.method(INTERFACE, in_signature='ai')
    def RefreshWindows(self, window_ids):
        self.server.control_command_refresh(*window_ids)

    @dbus.service.method(INTERFACE)
    def RefreshAllWindows(self):
        self.server.control_command_refresh(*self.server._id_to_window.keys())


    @dbus.service.method(INTERFACE, in_signature='s')
    def EnableDebug(self, category):
        add_debug_category(category)
        enable_debug_for(category)

    @dbus.service.method(INTERFACE, in_signature='s')
    def DisableDebug(self, category):
        remove_debug_category(category)
        disable_debug_for(category)
