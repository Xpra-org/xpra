# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display -- the parts that
# may import gtk.

import os

from wimpiggy.keys import grok_modifier_map
from xpra.xposix.xclipboard import ClipboardProtocolHelper
assert ClipboardProtocolHelper	#make pydev happy: this import is needed as it is part of the gui "interface"

from xpra.xposix.xsettings import XSettingsWatcher
from xpra.xposix.xroot_props import XRootPropWatcher
from xpra.platform.client_extras_base import ClientExtrasBase

from wimpiggy.log import Logger
log = Logger()


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts):
        ClientExtrasBase.__init__(self, client)
        client.connect("handshake-complete", self.handshake_complete)
        self.ROOT_PROPS = {
            "RESOURCE_MANAGER": "resource-manager"
            }
        if opts.pulseaudio:
            self.ROOT_PROPS["PULSE_COOKIE"] = "pulse-cookie"
            self.ROOT_PROPS["PULSE_ID"] = "pulse-id"
            self.ROOT_PROPS["PULSE_SERVER"] = "pulse-server"

        self.has_x11_bell = False
        try:
            from wimpiggy.lowlevel.bindings import device_bell
            self.has_x11_bell = device_bell is not None
        except ImportError, e:
            log.error("cannot import x11 bell bindings (will use gtk fallback) : %s", e)
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        self.has_pynotify = False
        try:
            import pynotify
            pynotify.init("Xpra")
            self.has_pynotify = True
        except ImportError, e:
            log.error("cannot import pynotify wrapper (turning notifications off) : %s", e)

    def exit(self):
        pass

    def handshake_complete(self, *args):
        log.info("handshake_complete(%s)" % str(args))
        self._xsettings_watcher = XSettingsWatcher()
        self._xsettings_watcher.connect("xsettings-changed",
                                        self._handle_xsettings_changed)
        self._handle_xsettings_changed()
        self._root_props_watcher = XRootPropWatcher(self.ROOT_PROPS.keys())
        self._root_props_watcher.connect("root-prop-changed",
                                        self._handle_root_prop_changed)
        self._root_props_watcher.notify_all()
        
    def _handle_xsettings_changed(self, *args):
        blob = self._xsettings_watcher.get_settings_blob()
        if blob is not None:
            self.client.send(["server-settings", {"xsettings-blob": blob}])

    def _handle_root_prop_changed(self, obj, prop, value):
        assert prop in self.ROOT_PROPS
        if value is not None:
            self.client.send(["server-settings",
                       {self.ROOT_PROPS[prop]: value.encode("utf-8")}])

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        if not self.has_x11_bell:
            import gtk.gdk
            gtk.gdk.beep()
            return
        from wimpiggy.lowlevel.bindings import device_bell      #@UnresolvedImport
        device_bell(window, device, bell_class, bell_id, percent, bell_name)

    def can_notify(self):
        return  self.has_pynotify
    
    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if self.dbus_id==dbus_id:
            log.error("remote dbus instance is the same as our local one, "
                      "cannot forward notification to ourself as this would create a loop")
            return
        import pynotify
        n = pynotify.Notification(summary, body)
        n.set_urgency(pynotify.URGENCY_LOW)
        n.set_timeout(expire_timeout)
        n.show()

    def close_notify(self, id):
        pass

    def get_keymap_spec(self):
        def get_keyboard_data(command, arg):
            # Find the client's current keymap so we can send it to the server:
            try:
                import subprocess
                cmd = [command, arg]
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
                (out,_) = process.communicate(None)
                if process.returncode==0:
                    return out
                log.error("'%s %s' failed with exit code %s\n" % (command, arg, process.returncode))
            except Exception, e:
                log.error("error running '%s %s': %s\n" % (command, arg, e))
            return None
        xkbmap_print = get_keyboard_data("setxkbmap", "-print")
        if xkbmap_print is None:
            log.error("your keyboard mapping will probably be incorrect unless you are using a 'us' layout");
        xkbmap_query = get_keyboard_data("setxkbmap", "-query")
        if xkbmap_query is None and xkbmap_print is not None:
            log.error("the server will try to guess your keyboard mapping, which works reasonably well in most cases");
            log.error("however, upgrading 'setxkbmap' to a version that supports the '-query' parameter is preferred");
        xmodmap_data = get_keyboard_data("xmodmap", "-pke");
        return xkbmap_print, xkbmap_query, xmodmap_data

    def grok_modifier_map(self, display_source):
        return grok_modifier_map(display_source)
