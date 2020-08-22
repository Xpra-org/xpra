#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2015-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections import namedtuple
import dbus.service

from xpra.dbus.helper import dbus_to_native, native_to_dbus
from xpra.dbus.common import init_session_bus
from xpra.server.dbus.dbus_server_base import DBUS_Server_Base, INTERFACE, BUS_NAME
from xpra.util import parse_scaling_value, from0to100, DETACH_REQUEST
from xpra.log import (
    Logger,
    add_debug_category, remove_debug_category,
    disable_debug_for, enable_debug_for,
    )
log = Logger("dbus", "server")


Rectangle = namedtuple("Workarea", "x,y,width,height")


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


class DBUS_Server(DBUS_Server_Base):

    def __init__(self, server=None, extra=""):
        bus = init_session_bus()
        name = BUS_NAME
        if extra:
            name += extra.replace(".", "_").replace(":", "_")
        DBUS_Server_Base.__init__(self, bus, server, name)
        self._properties.update({
            "idle-timeout"          : ("idle_timeout",          ni),
            "server-idle-timeout"   : ("server_idle_timeout",   ni),
            "name"                  : ("session_name",          ns),
            })


    @dbus.service.method(INTERFACE, in_signature='i')
    def Focus(self, wid):
        wid = ni(wid)
        self.log(".Focus(%i)", wid)
        self.server.control_command_focus(wid)

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
        c = ns(command)
        self.log(".Start(%s)", c)
        self.server.do_control_command_start(True, c)

    @dbus.service.method(INTERFACE, in_signature='s')
    def StartChild(self, command):
        c = ns(command)
        self.log(".StartChild(%s)", c)
        self.server.do_control_command_start(False, c)

    @dbus.service.method(INTERFACE, in_signature='sb')
    def ToggleFeature(self, feature, state):
        f, s = ns(feature), ns(state)
        self.log(".ToggleFeature(%s, %s)", f, s)
        self.server.control_command_toggle_feature(f, s)


    @dbus.service.method(INTERFACE, in_signature='i')
    def KeyPress(self, keycode):
        k = ni(keycode)
        self.log(".KeyPress(%i)", k)
        self.server.control_command_key(str(k), press=True)

    @dbus.service.method(INTERFACE, in_signature='i')
    def KeyRelease(self, keycode):
        k = ni(keycode)
        self.log(".KeyRelease(%i)", k)
        self.server.control_command_key(str(k), press=False)

    @dbus.service.method(INTERFACE)
    def ClearKeysPressed(self):
        self.log(".ClearKeysPressed()")
        self.server.clear_keys_pressed()

    @dbus.service.method(INTERFACE, in_signature='ii')
    def SetKeyboardRepeat(self, repeat_delay, repeat_interval):
        d, i = ni(repeat_delay), ni(repeat_interval)
        self.log(".SetKeyboardRepeat(%i, %i)", d, i)
        self.server.set_keyboard_repeat(d, i)


    @dbus.service.method(INTERFACE, in_signature='iii')
    def MovePointer(self, wid, x, y):
        wid, x, y = ni(wid), ni(x), ni(y)
        self.log(".MovePointer(%i, %i, %i)", wid, x, y)
        self.server._move_pointer(ni(wid), (ni(x), ni(y)))

    @dbus.service.method(INTERFACE, in_signature='ib')
    def MouseClick(self, button, pressed):
        button, pressed = ni(button), nb(pressed)
        self.log(".MouseClick%s", (button, pressed))
        device_id = -1
        self.server.button_action(None, button, pressed, device_id)


    @dbus.service.method(INTERFACE, in_signature='iiii')
    def SetWorkarea(self, x, y, w, h):
        x, y, w, h = ni(x), ni(y), ni(w), ni(h)
        self.log(".SetWorkarea%s", (x, y, w, h))
        workarea = Rectangle(x=x, y=y, width=w, height=h)
        self.server.set_workarea(workarea)


    @dbus.service.method(INTERFACE, in_signature='iiiii')
    def SetVideoRegion(self, wid, x, y, w, h):
        wid, x, y, w, h = ni(wid), ni(x), ni(y), ni(w), ni(h)
        self.log(".SetVideoRegion%s", (wid, x, y, w, h))
        self.server.control_command_video_region(wid, x, y, w, h)

    @dbus.service.method(INTERFACE, in_signature='ib')
    def SetVideoRegionEnabled(self, wid, enabled):
        wid, enabled = ni(wid), nb(enabled)
        self.log(".SetVideoRegionEnabled(%i, %s)", wid, enabled)
        self.server.control_command_video_region_enabled(wid, enabled)

    @dbus.service.method(INTERFACE, in_signature='ib')
    def SetVideoRegionDetection(self, wid, detection):
        wid, detection = ni(wid), nb(detection)
        self.log(".SetVideoRegionDetection(%i, %s)", wid, detection)
        self.server.control_command_video_region_detection(wid, detection)

    @dbus.service.method(INTERFACE, in_signature='iaai')
    def SetVideoRegionExclusionZones(self, wid, zones):
        wid = ni(wid)
        nzones = []
        for zone in zones:
            nzones.append([ni(x) for x in zone])
        log("SetVideoRegionExclusionZones(%i, %s)", wid, nzones)
        self.server.control_command_video_region_exclusion_zones(wid, nzones)

    @dbus.service.method(INTERFACE, in_signature='i')
    def ResetVideoRegion(self, wid):
        wid = ni(wid)
        self.log(".ResetVideoRegion(%i)", wid)
        self.server.control_command_reset_video_region(wid)



    @dbus.service.method(INTERFACE, in_signature='ii')
    def LockBatchDelay(self, wid, delay):
        wid, delay = ni(wid), ni(delay)
        self.log(".LockBatchDelay(%i, %i)", wid, delay)
        self.server.control_command_lock_batch_delay(wid, delay)

    @dbus.service.method(INTERFACE, in_signature='i')
    def UnlockBatchDelay(self, wid):
        wid = ni(wid)
        self.log(".UnlockBatchDelay(%i)", wid)
        self.server.control_command_unlock_batch_delay(wid)


    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{is}')
    def ListWindows(self):
        d = {}
        for wid, window in self.server._id_to_window.items():
            try:
                d[wid] = window.get_property("title")
            except Exception:
                d[wid] = str(window)
        self.log(".ListWindows()=%s", d)
        return d


    @dbus.service.method(INTERFACE, in_signature='s')
    def SetLock(self, lock):
        s = ns(lock)
        self.log(".SetLock(%s)", s)
        self.server.control_command_set_lock(s)

    @dbus.service.method(INTERFACE, in_signature='s')
    def SetSharing(self, sharing):
        s = ns(sharing)
        self.log(".SetSharing(%s)", s)
        self.server.control_command_set_sharing(s)


    @dbus.service.method(INTERFACE, in_signature='s')
    def SetUIDriver(self, uuid):
        s = ns(uuid)
        self.log(".SetUIDriver(%s)", s)
        self.server.control_command_set_ui_driver(s)


    @dbus.service.method(INTERFACE, in_signature='i')
    def SetIdleTimeout(self, value):
        nvalue = ni(value)
        self.log(".SetIdleTimeout(%s)", nvalue)
        self.server.control_command_idle_timeout(nvalue)


    @dbus.service.method(INTERFACE, in_signature='ii')
    def MoveWindowToWorkspace(self, wid, workspace):
        wid, workspace = ni(wid), ni(workspace)
        self.log(".MoveWindowToWorkspace(%i, %i)", wid, workspace)
        self.server.control_command_workspace(wid, workspace)

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowScaling(self, wid, scaling):
        wid, scaling = ni(wid), ns(scaling)
        self.log(".SetWindowScaling(%i, %s)", wid, scaling)
        s = parse_scaling_value(scaling)
        self.server.control_command_scaling(s, wid)

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowScalingControl(self, wid, scaling_control):
        wid = ni(wid)
        self.log(".SetWindowScalingControl(%i, %s)", wid, scaling_control)
        if scaling_control.lower() in ("auto", "on"):
            sc = None
        else:
            sc = from0to100(int(ns(scaling_control)))
        self.server.control_command_scaling_control(sc, wid)

    @dbus.service.method(INTERFACE, in_signature='is')
    def SetWindowEncoding(self, wid, encoding):
        wid, encoding = ni(wid), ns(encoding)
        self.log(".SetWindowEncoding(%i, %s)", wid, encoding)
        self.server.control_command_encoding(encoding, wid)

    @dbus.service.method(INTERFACE, in_signature='i')
    def RefreshWindow(self, wid):
        wid = ni(wid)
        self.log(".RefreshWindow(%i)", wid)
        self.server.control_command_refresh(wid)


    @dbus.service.method(INTERFACE, in_signature='ai')
    def RefreshWindows(self, window_ids):
        wids = [ni(x) for x in window_ids]
        self.log(".RefreshWindows(%s)", wids)
        self.server.control_command_refresh(*wids)

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
        c = ns(category)
        self.log(".EnableDebug(%s)", c)
        add_debug_category(c)
        enable_debug_for(c)

    @dbus.service.method(INTERFACE, in_signature='s')
    def DisableDebug(self, category):
        c = ns(category)
        self.log(".DisableDebug(%s)", c)
        remove_debug_category(c)
        disable_debug_for(c)


    @dbus.service.method(INTERFACE, in_signature='isss')
    def SendNotification(self, nid, title, message, uuids):
        nid, title, message, uuids = ni(nid), ns(title), ns(message), ns(uuids)
        self.log(".SendNotification%s", (nid, title, message, uuids))
        self.server.control_command_send_notification(nid, title, message, uuids)

    @dbus.service.method(INTERFACE, in_signature='is')
    def CloseNotification(self, nid, uuids):
        nid, uuids = ni(nid), ns(uuids)
        self.log(".CloseNotification%s", (nid, uuids))
        self.server.control_command_close_notification(nid, uuids)


    @dbus.service.method(INTERFACE, in_signature='sii')
    def SetClipboardProperties(self, direction, max_copyin, max_copyout):
        #keep direction unchanged if not specified
        max_copyin, max_copyout = ni(max_copyin), ni(max_copyout)
        direction = ns(direction) or self.server.clipboard_direction
        self.log(".SetClipboardProperties%s", (direction, max_copyin, max_copyout))
        self.server.control_command_clipboard_direction(direction, max_copyin, max_copyout)


    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{ss}')
    def ListClients(self):
        d = {}
        for p, source in self.server._server_sources.items():
            try:
                d[source.uuid] = str(p)
            except KeyError:
                d[str(source)] = str(p)
        self.log(".ListClients()=%s", d)
        return d

    @dbus.service.method(INTERFACE, in_signature='s')
    def DetachClient(self, uuid):
        s = ns(uuid)
        self.log(".DetachClient(%s)", s)
        for p, source in self.server._server_sources.items():
            if source.uuid==s:
                self.log("matched %s", source)
                self.server.disconnect_client(p, DETACH_REQUEST)

    @dbus.service.method(INTERFACE)
    def DetachAllClients(self):
        self.log(".DetachAllClients() will detach: %s", self.server._server_sources)
        for p in self.server._server_sources.keys():
            self.server.disconnect_client(p, DETACH_REQUEST)


    @dbus.service.method(INTERFACE, in_signature='as')
    def SendUIClientCommand(self, args):
        nargs = n(args)
        log("SendUIClientCommand(%s)", nargs)
        for src in self.server._server_sources.values():
            if src.ui_client:
                src.send_client_command(*nargs)


    @dbus.service.method(INTERFACE, in_signature='', out_signature='a{sv}', async_callbacks=("callback", "errback"))
    def GetAllInfo(self, callback, errback):
        self.log(".GetAllInfo()")
        def gotinfo(_proto, info):
            try:
                v = dbus.types.Dictionary((str(k), native_to_dbus(v)) for k,v in info.items())
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
        def gotinfo(_proto, info):
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
