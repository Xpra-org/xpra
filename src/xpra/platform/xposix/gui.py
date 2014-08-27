# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("posix")
eventlog = Logger("events", "posix")

from xpra.gtk_common.gobject_compat import get_xid, is_gtk3
from xpra.gtk_common.error import trap, XError

device_bell = None

def get_native_notifier_classes():
    ncs = []
    try:
        from xpra.client.notifications.dbus_notifier import DBUS_Notifier_factory
        ncs.append(DBUS_Notifier_factory)
    except Exception as e:
        log("cannot load dbus notifier: %s", e)
    try:
        from xpra.client.notifications.pynotify_notifier import PyNotify_Notifier
        ncs.append(PyNotify_Notifier)
    except Exception as e:
        log("cannot load pynotify notifier: %s", e)
    return ncs

def get_native_tray_classes():
    try:
        from xpra.platform.xposix.appindicator_tray import AppindicatorTray, can_use_appindicator
        if can_use_appindicator():
            return [AppindicatorTray]
    except Exception as e:
        log("cannot load appindicator tray: %s", e)
    return []

def get_native_system_tray_classes():
    #appindicator can be used for both
    return get_native_tray_classes()


def system_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
    global device_bell
    if device_bell is False:
        #failed already
        return False
    def x11_bell():
        global device_bell
        if device_bell is None:
            #try to load it:
            from xpra.x11.bindings.keyboard_bindings import X11KeyboardBindings       #@UnresolvedImport
            device_bell = X11KeyboardBindings().device_bell
        device_bell(get_xid(window), device, bell_class, bell_id, percent, bell_name)
    try:
        trap.call_synced(x11_bell)
        return  True
    except XError as e:
        log.error("error using device_bell: %s, switching native X11 bell support off", e)
        device_bell = False
        return False


class ClientExtras(object):
    def __init__(self, client, opts):
        self.client = client
        self._xsettings_watcher = None
        self._root_props_watcher = None
        self.system_bus = None
        self.upower_resuming_match = None
        self.upower_sleeping_match = None
        self.login1_match = None
        if client.xsettings_enabled:
            self.setup_xprops()
        self.setup_dbus_signals()

    def cleanup(self):
        log("cleanup() xsettings_watcher=%s, root_props_watcher=%s", self._xsettings_watcher, self._root_props_watcher)
        if self._xsettings_watcher:
            self._xsettings_watcher.cleanup()
            self._xsettings_watcher = None
        if self._root_props_watcher:
            self._root_props_watcher.cleanup()
            self._root_props_watcher = None
        if self.system_bus:
            bus = self.system_bus
            log("cleanup() system bus=%s, matches: %s", bus, (self.upower_resuming_match, self.upower_sleeping_match, self.login1_match))
            self.system_bus = None
            if self.upower_resuming_match:
                bus._clean_up_signal_match(self.upower_resuming_match)
            if self.upower_sleeping_match:
                bus._clean_up_signal_match(self.upower_sleeping_match)
            if self.login1_match:
                bus._clean_up_signal_match(self.login1_match)

    def resuming_callback(self, *args):
        eventlog("resuming_callback%s", args)
        self.client.resume()

    def sleeping_callback(self, *args):
        eventlog("sleeping_callback%s", args)
        self.client.suspend()


    def setup_dbus_signals(self):
        try:
            from xpra.x11.dbus_common import init_system_bus
            bus = init_system_bus()
            self.system_bus = bus
            log("setup_dbus_signals() system bus=%s", bus)
        except Exception as e:
            log.warn("dbus setup error: %s", e)
            return

        #the UPower signals:
        try:
            bus_name    = 'org.freedesktop.UPower'
            log("bus has owner(%s)=%s", bus_name, bus.name_has_owner(bus_name))
            iface_name  = 'org.freedesktop.UPower'
            self.upower_resuming_match = bus.add_signal_receiver(self.resuming_callback, 'Resuming', iface_name, bus_name)
            self.upower_sleeping_match = bus.add_signal_receiver(self.sleeping_callback, 'Sleeping', iface_name, bus_name)
            eventlog("listening for 'Resuming' and 'Sleeping' signals on %s", iface_name)
        except Exception as e:
            eventlog("failed to setup UPower event listener: %s", e)

        #the "logind" signals:
        try:
            bus_name    = 'org.freedesktop.login1'
            log("bus has owner(%s)=%s", bus_name, bus.name_has_owner(bus_name))
            def sleep_event_handler(suspend):
                if suspend:
                    self.sleeping_callback()
                else:
                    self.resuming_callback()
            iface_name  = 'org.freedesktop.login1.Manager'
            self.login1_match = bus.add_signal_receiver(sleep_event_handler, 'PrepareForSleep', iface_name, bus_name)
            eventlog("listening for 'PrepareForSleep' signal on %s", iface_name)
        except Exception as e:
            eventlog("failed to setup login1 event listener: %s", e)

    def setup_xprops(self):
        #wait for handshake to complete:
        self.client.connect("handshake-complete", self.do_setup_xprops)

    def do_setup_xprops(self, *args):
        log("do_setup_xprops(%s)", args)
        if is_gtk3():
            log("x11 root properties and XSETTINGS are not supported yet with GTK3")
            return
        ROOT_PROPS = ["RESOURCE_MANAGER", "_NET_WORKAREA", "_NET_CURRENT_DESKTOP"]
        try:
            from xpra.x11.xsettings import XSettingsWatcher
            from xpra.x11.xroot_props import XRootPropWatcher
            if self._xsettings_watcher is None:
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
            if self._root_props_watcher is None:
                self._root_props_watcher = XRootPropWatcher(ROOT_PROPS)
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                #ensure we get the initial value:
                self._root_props_watcher.do_notify("RESOURCE_MANAGER")
        except ImportError as e:
            log.error("failed to load X11 properties/settings bindings: %s - root window properties will not be propagated", e)

    def _handle_xsettings_changed(self, *args):
        try:
            settings = self._xsettings_watcher.get_settings()
        except:
            log.error("failed to get XSETTINGS", exc_info=True)
            return
        log("xsettings_changed new value=%s", settings)
        if settings is not None:
            self.client.send("server-settings", {"xsettings-blob": settings})

    def _handle_root_prop_changed(self, obj, prop):
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop=="RESOURCE_MANAGER":
            if not self.client.xsettings_tuple:
                log.warn("xsettings tuple format not supported, update ignored")
                return
            import gtk.gdk
            root = gtk.gdk.get_default_root_window()
            from xpra.x11.gtk_x11.prop import prop_get
            value = prop_get(root, "RESOURCE_MANAGER", "latin1", ignore_errors=True)
            if value is not None:
                self.client.send("server-settings", {"resource-manager" : value.encode("utf-8")})
        elif prop=="_NET_WORKAREA":
            self.client.screen_size_changed("from %s event" % self._root_props_watcher)
        elif prop=="_NET_CURRENT_DESKTOP":
            self.client.workspace_changed("from %s event" % self._root_props_watcher)
        else:
            log.error("unknown property %s", prop)
