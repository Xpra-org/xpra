# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display -- the parts that
# may import gtk.

import sys
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
        self.setup_menu(True)
        self.setup_tray(opts.tray_icon)
        self.setup_xprops(opts.pulseaudio)
        self.setup_x11_bell()
        self.setup_pynotify()

    def exit(self):
        if self.tray_widget:
            self.tray_widget.set_visible(False)
            self.tray_widget = None

    def get_data_dir(self):
        #is there a better/cleaner way?
        options = ["/usr/share/xpra", "/usr/local/share/xpra"]
        if sys.executable.startswith("/usr/local"):
            options.reverse()
        for x in options:
            if os.path.exists(x):
                return x
        return  os.getcwd()

    def setup_tray(self, tray_icon_filename):
        self.tray_widget = None
        try:
            import pygtk
            pygtk.require("2.0")
            import gtk
            self.tray_widget = gtk.StatusIcon()
            self.tray_widget.connect('popup-menu', self.popup_menu)
            self.tray_widget.connect('activate', self.activate_menu)
            filename = tray_icon_filename or os.path.join(self.get_data_dir(), "icons", "xpra.png")
            if filename and os.path.exists(filename):
                pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
                self.tray_widget.set_from_pixbuf(pixbuf)
            def show_tray(*args):
                log.info("showing tray")
                #session_name will get set during handshake
                self.tray_widget.set_tooltip(self.client.session_name)
                self.tray_widget.set_visible(True)
            self.client.connect("handshake-complete", show_tray)
        except Exception, e:
            log.error("failed to setup tray: %s", e)

    def setup_pynotify(self):
        self.dbus_id = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
        self.has_pynotify = False
        try:
            import pynotify
            pynotify.init("Xpra")
            self.has_pynotify = True
        except ImportError, e:
            log.error("cannot import pynotify wrapper (turning notifications off) : %s", e)

    def setup_x11_bell(self):
        self.has_x11_bell = False
        try:
            from wimpiggy.lowlevel.bindings import device_bell
            self.has_x11_bell = device_bell is not None
        except ImportError, e:
            log.error("cannot import x11 bell bindings (will use gtk fallback) : %s", e)

    def setup_xprops(self, pulseaudio):
        self.client.connect("handshake-complete", self.setup_xprops)
        self.ROOT_PROPS = {
            "RESOURCE_MANAGER": "resource-manager"
            }
        if pulseaudio:
            self.ROOT_PROPS["PULSE_COOKIE"] = "pulse-cookie"
            self.ROOT_PROPS["PULSE_ID"] = "pulse-id"
            self.ROOT_PROPS["PULSE_SERVER"] = "pulse-server"
        def handshake_complete(*args):
            log.info("handshake_complete(%s)" % str(args))
            self._xsettings_watcher = XSettingsWatcher()
            self._xsettings_watcher.connect("xsettings-changed",
                                            self._handle_xsettings_changed)
            self._handle_xsettings_changed()
            self._root_props_watcher = XRootPropWatcher(self.ROOT_PROPS.keys())
            self._root_props_watcher.connect("root-prop-changed",
                                            self._handle_root_prop_changed)
            self._root_props_watcher.notify_all()
        self.client.connect("handshake-complete", handshake_complete)

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

    def get_keyboard_repeat(self):
        try:
            from wimpiggy.lowlevel import get_key_repeat_rate
            delay, interval = get_key_repeat_rate()
            return delay,interval
        except Exception, e:
            log.error("failed to get keyboard repeat rate: %s", e)
        return None

    def grok_modifier_map(self, display_source):
        return grok_modifier_map(display_source)
