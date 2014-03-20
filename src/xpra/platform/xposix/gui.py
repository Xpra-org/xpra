# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger("posix")

try:
    import gtk.gdk
    from xpra.x11.gtk_x11.error import trap, XError
    from xpra.x11.bindings import X11KeyboardBindings       #@UnresolvedImport
    device_bell = X11KeyboardBindings().device_bell
except:
    device_bell = None


def get_native_notifier_classes():
    ncs = []
    try:
        from xpra.client.notifications.dbus_notifier import DBUS_Notifier_factory
        ncs.append(DBUS_Notifier_factory)
    except Exception, e:
        log("cannot load dbus notifier: %s", e)
    try:
        from xpra.client.notifications.pynotify_notifier import PyNotify_Notifier
        ncs.append(PyNotify_Notifier)
    except Exception, e:
        log("cannot load pynotify notifier: %s", e)
    return ncs

def get_native_tray_classes():
    try:
        from xpra.platform.xposix.appindicator_tray import AppindicatorTray, can_use_appindicator
        if can_use_appindicator():
            return [AppindicatorTray]
    except Exception, e:
        log("cannot load appindicator tray: %s", e)
    return []

def get_native_system_tray_classes():
    #appindicator can be used for both
    return get_native_tray_classes()

def system_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
    global device_bell
    if device_bell is None:
        return False
    try:
        trap.call_synced(device_bell, window.xid, device, bell_class, bell_id, percent, bell_name)
        return  True
    except XError, e:
        log.error("error using device_bell: %s, switching native X11 bell support off", e)
        device_bell = None
        return False


class ClientExtras(object):
    def __init__(self, client):
        self.client = client
        self._xsettings_watcher = None
        self._root_props_watcher = None
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


    def resuming_callback(self, *args):
        self.client.resume()

    def sleeping_callback(self, *args):
        self.client.suspend()


    def setup_dbus_signals(self):
        try:
            from xpra.x11.dbus_common import init_system_bus
            bus = init_system_bus()
        except Exception, e:
            log.warn("dbus setup error: %s", e)
            return

        #the UPower signals:
        try:
            iface_name  = 'org.freedesktop.UPower'
            bus_name    = 'org.freedesktop.UPower'
            bus.add_signal_receiver(self.resuming_callback, 'Resuming', iface_name, bus_name)
            bus.add_signal_receiver(self.sleeping_callback, 'Sleeping', iface_name, bus_name)
            log("listening for 'Resuming' and 'Sleeping' signals on %s", iface_name)
        except Exception, e:
            log("failed to setup UPower event listener: %s", e)

        #the "logind" signals:
        try:
            def sleep_event_handler(suspend):
                if suspend:
                    self.sleeping_callback()
                else:
                    self.resuming_callback()
            iface_name  = 'org.freedesktop.login1.Manager'
            bus_name    = 'org.freedesktop.login1'
            bus.add_signal_receiver(sleep_event_handler, 'PrepareForSleep', iface_name, bus_name)
            log("listening for 'PrepareForSleep' signal on %s", iface_name)
        except Exception, e:
            log("failed to setup login1 event listener: %s", e)

    def setup_xprops(self):
        #wait for handshake to complete:
        self.client.connect("handshake-complete", self.do_setup_xprops)

    def do_setup_xprops(self, *args):
        log.debug("do_setup_xprops(%s)", args)
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
        except ImportError, e:
            log.error("failed to load X11 properties/settings bindings: %s - root window properties will not be propagated", e)

    def _handle_xsettings_changed(self, *args):
        try:
            blob = self._xsettings_watcher.get_settings_blob()
        except:
            log.error("failed to get XSETTINGS", exc_info=True)
            return
        log("xsettings_changed new value=%s", blob)
        if blob is not None:
            self.client.send("server-settings", {"xsettings-blob": blob})

    def _handle_root_prop_changed(self, obj, prop):
        log("root_prop_changed(%s, %s)", obj, prop)
        if prop=="RESOURCE_MANAGER":
            if not self.client.xsettings_tuple:
                log.warn("xsettings tuple format not supported, update ignored")
                return
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
