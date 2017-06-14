#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.dbus.helper import dbus_to_native, native_to_dbus
from xpra.dbus.common import init_session_bus
from xpra.util import parse_scaling_value, from0to100, AdHocStruct
import dbus.service

from xpra.log import Logger, add_debug_category, remove_debug_category, disable_debug_for, enable_debug_for
log = Logger("dbus", "server")

BUS_NAME = "org.xpra.Server"
INTERFACE = "org.xpra.Server"
PATH = "/org/xpra/Server"


def n(*args):
    return dbus_to_native(*args)
def ni(*args):
    return int(n(*args))
def ns(*args):
    return str(n(*args))
def nb(*args):
    return bool(n(*args))


def stoms(v):
    return int(v*1000.0)


class DBUS_Server(dbus.service.Object):

    def __init__(self, server=None, extra=""):
        self.server = server
        session_bus = init_session_bus()
        name = BUS_NAME
        path = PATH
        if extra:
            name += extra.replace(".", "_").replace(":", "_")
        bus_name = dbus.service.BusName(name, session_bus)
        dbus.service.Object.__init__(self, bus_name, path)
        self.log("(%s)", server)
        self._properties = {
                            "idle-timeout"          : ("idle_timeout",          ni),
                            "server-idle-timeout"   : ("server_idle_timeout",   ni),
                            "name"                  : ("session_name",          ns),
                            "sharing"               : ("sharing",               nb),
                            }

    def cleanup(self):
        try:
            log("calling %s", self.remove_from_connection)
            self.remove_from_connection()
        except Exception as e:
            log.error("Error removing the DBUS server:")
            log.error(" %s", e)


    def log(self, fmt, *args):
        log("%s"+fmt, INTERFACE, *args)


    @dbus.service.signal(INTERFACE, signature='sas')
    def Event(self, event, args):
        self.log(".Event(%s, %s)", event, args);


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
        self.log(".Focus(%i)", wid)
        self.server.control_command_focus(ni(wid))

    @dbus.service.method(INTERFACE, in_signature='')
    def Suspend(self):
        self.log(".Suspend()")
        self.server.control_command_suspend()

    @dbus.service.method(INTERFACE, in_signature='')
    def Resume(self):
        self.log(".Resume()")
        self.server.control_command_resume()

    @dbus.service.method(INTERFACE, in_signature='')
    def Ungrab(self):
        self.log(".Ungrab()")
        self.server.control_command_resume()


    @dbus.service.method(INTERFACE, in_signature='s')
    def Start(self, command):
        self.log(".Start()")
        self.server.do_control_command_start(True, ns(command))

    @dbus.service.method(INTERFACE, in_signature='s')
    def StartChild(self, command):
        self.log(".StartChild(%s)", command)
        self.server.do_control_command_start(False, ns(command))

    @dbus.service.method(INTERFACE, in_signature='sb')
    def ToggleFeature(self, feature, state):
        self.log(".ToggleFeature(%s, %s)", feature, state)
        self.server.control_command_toggle_feature(feature, state)


    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyPress(self, keycode):
        self.log(".KeyPress(%i)", keycode)
        self.server.control_command_key(ns(keycode), press=True)

    @dbus.service.method(INTERFACE, in_signature='s')
    def KeyRelease(self, keycode):
        self.log(".KeyRelease(%i)", keycode)
        self.server.control_command_key(ns(keycode), press=False)

    @dbus.service.method(INTERFACE)
    def ClearKeysPressed(self):
        self.log(".ClearKeysPressed()")
        self.server._clear_keys_pressed()

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetKeyboardRepeat(self, repeat_delay, repeat_interval):
        self.log(".SetKeyboardRepeat(%i, %i)", repeat_delay, repeat_interval)
        self.server.set_keyboard_repeat(ni(repeat_delay), ni(repeat_interval))


    @dbus.service.method(INTERFACE, in_signature='iii')
    def MovePointer(self, wid, x, y):
        self.log(".MovePointer(%i, %i, %i)", wid, x, y)
        self.server._move_pointer(ni(wid), (ni(x), ni(y)))

    @dbus.service.method(INTERFACE, in_signature='ib')
    def MouseClick(self, button, pressed):
        self.log(".MouseClick%s", (button, pressed))
        device_id = -1
        self.server.button_action(ni(button), nb(pressed), device_id)


    @dbus.service.method(INTERFACE, in_signature='iiii')
    def SetWorkarea(self, x, y, w, h):
        self.log(".SetWorkarea%s", (x, y, w, h))
        workarea = AdHocStruct()
        workarea.x, workarea.y, workarea.width, workarea.height = ni(x), ni(y), ni(w), ni(h)
        self.server.set_workarea(workarea)


    @dbus.service.method(INTERFACE, in_signature='iiiii')
    def SetVideoRegion(self, wid, x, y, w, h):
        self.log(".SetVideoRegion%s", (wid, x, y, w, h))
        self.server.control_command_video_region(ni(wid), ni(x), ni(y), ni(w), ni(h))

    @dbus.service.method(INTERFACE, in_signature='ib')
    def SetVideoRegionEnabled(self, wid, enabled):
        self.log(".SetVideoRegionEnabled(%i, %s)", wid, enabled)
        self.server.control_command_video_region_enabled(ni(wid), nb(enabled))

    @dbus.service.method(INTERFACE, in_signature='ib')
    def SetVideoRegionDetection(self, wid, detection):
        self.log(".SetVideoRegionDetection(%i, %s)", wid, detection)
        self.server.control_command_video_region_detection(ni(wid), nb(detection))

    @dbus.service.method(INTERFACE, in_signature='iaai')
    def SetVideoRegionExclusionZones(self, wid, zones):
        log("SetVideoRegionExclusionZones(%i, %s)", wid, zones)
        nzones = []
        for zone in zones:
            nzones.append([ni(x) for x in zone])
        self.server.control_command_video_region_exclusion_zones(ni(wid), nzones)

    @dbus.service.method(INTERFACE, in_signature='i')
    def ResetVideoRegion(self, wid):
        self.log(".ResetVideoRegion(%i)", wid)
        self.server.control_command_reset_video_region(ni(wid))



    @dbus.service.method(INTERFACE, in_signature='ii')
    def LockBatchDelay(self, wid, delay):
        self.log(".LockBatchDelay(%i, %i)", wid, delay)
        self.server.control_command_lock_batch_delay(ni(wid), ni(delay))

    @dbus.service.method(INTERFACE, in_signature='i')
    def UnlockBatchDelay(self, wid):
        self.log(".UnlockBatchDelay(%i)", wid)
        self.server.control_command_unlock_batch_delay(ni(wid))


    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{is}')
    def ListWindows(self):
        d = {}
        for wid, window in self.server._id_to_window.items():
            try:
                d[wid] = window.get_property("title")
            except:
                d[wid] = str(window)
        self.log(".ListWindows()=%s", d)
        return d


    @dbus.service.method(INTERFACE, in_signature='s')
    def SetClipboardDirection(self, direction):
        self.log(".SetClipboardDirection(%s)", direction)
        self.server.control_command_clipboard_direction(ns(direction))


    @dbus.service.method(INTERFACE, in_signature='ii')
    def MoveWindowToWorkspace(self, wid, workspace):
        self.log(".MoveWindowToWorkspace(%i, %i)", wid, workspace)
        self.server.control_command_workspace(ni(wid), ni(workspace))

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowScaling(self, wid, scaling):
        self.log(".SetWindowScaling(%i, %s)", wid, scaling)
        s = parse_scaling_value(ns(scaling))
        self.server.control_command_scaling(s, ni(wid))

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetWindowScalingControl(self, wid, scaling_control):
        self.log(".SetWindowScalingControl(%i, %i)", wid, scaling_control)
        sc = from0to100(ni(scaling_control))
        self.server.control_command_scaling_control(sc, ni(wid))

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowEncoding(self, wid, encoding):
        self.log(".SetWindowEncoding(%i, %i)", wid, encoding)
        self.server.control_command_encoding(ns(encoding), ni(wid))

    @dbus.service.method(INTERFACE, in_signature='i')
    def RefreshWindow(self, wid):
        self.log(".RefreshWindow(%i)", wid)
        self.server.control_command_refresh(ni(wid))


    @dbus.service.method(INTERFACE, in_signature='ai')
    def RefreshWindows(self, window_ids):
        self.log(".RefreshWindows(%s)", window_ids)
        self.server.control_command_refresh(*(ni(x) for x in window_ids))

    @dbus.service.method(INTERFACE)
    def RefreshAllWindows(self):
        self.log(".RefreshAllWindows()")
        self.server.control_command_refresh(*self.server._id_to_window.keys())


    @dbus.service.method(INTERFACE)
    def ResetWindowFilters(self):
        self.log(".ResetWindowFilters()")
        self.server.reset_window_filters()


    @dbus.service.method(INTERFACE, in_signature='s')
    def EnableDebug(self, category):
        self.log(".EnableDebug(%s)", category)
        c = ns(category)
        add_debug_category(c)
        enable_debug_for(c)

    @dbus.service.method(INTERFACE, in_signature='s')
    def DisableDebug(self, category):
        self.log(".DisableDebug(%s)", category)
        c = ns(category)
        remove_debug_category(c)
        disable_debug_for(c)


    @dbus.service.method(INTERFACE, in_signature='isss')
    def SendNotification(self, nid, title, message, uuids):
        self.log(".SendNotification%s", (nid, title, message, uuids))
        self.server.control_command_send_notification(ni(nid), ns(title), ns(message), ns(uuids))

    def CloseNotification(self, nid, uuids):
        self.log(".CloseNotification%s", (nid, uuids))
        self.server.control_command_close_notification(ni(nid), ns(uuids))


    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{ss}')
    def ListClients(self):
        d = {}
        for p, source in self.server._server_sources.items():
            try:
                d[source.uuid] = str(p)
            except:
                d[str(source)] = str(p)
        self.log(".ListClients()=%s", d)
        return d

    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{sv}', async_callbacks=("callback", "errback"))
    def GetAllInfo(self, callback, errback):
        self.log(".GetAllInfo()")
        def gotinfo(proto=None, info={}):
            try:
                v =  dbus.types.Dictionary((str(k), native_to_dbus(v)) for k,v in info.items())
                #v =  native_to_dbus(info)
                log("native_to_dbus(..)=%s", v)
                callback(v)
            except Exception as e:
                log("GetAllInfo:gotinfo", exc_info=True)
                errback(str(e))
        v = self.server.get_all_info(gotinfo)
        self.log(".GetAllInfo()=%s", v)
        return v

    @dbus.service.method(INTERFACE, in_signature='s', out_signature='a{sv}', async_callbacks=("callback", "errback"))
    def GetInfo(self, subsystem, callback, errback):
        self.log(".GetInfo(%s)", subsystem)
        def gotinfo(proto=None, info={}):
            sub = info.get(subsystem)
            try:
                v =  dbus.types.Dictionary((str(k), native_to_dbus(v)) for k,v in sub.items())
                log("native_to_dbus(..)=%s", v)
                callback(v)
            except Exception as e:
                log("GetInfo:gotinfo", exc_info=True)
                errback(str(e))
        v = self.server.get_all_info(gotinfo)
        self.log(".GetInfo(%s)=%s", subsystem, v)
        return v
