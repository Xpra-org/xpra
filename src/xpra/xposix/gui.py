# This file is part of Parti.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# Platform-specific code for Posix systems with X11 display -- the parts that
# may import gtk.

from wimpiggy.keys import grok_modifier_map
assert grok_modifier_map		#make pydev happy: this import is needed as it is part of the gui "interface"

from xpra.xposix.xclipboard import ClipboardProtocolHelper
assert ClipboardProtocolHelper	#make pydev happy: this import is needed as it is part of the gui "interface"

from xpra.xposix.xsettings import XSettingsWatcher
from xpra.xposix.xroot_props import XRootPropWatcher

from wimpiggy.log import Logger
log = Logger()

class ClientExtras(object):
    def __init__(self, send_packet_cb, pulseaudio, opts):
        self.send = send_packet_cb
        self.ROOT_PROPS = {
            "RESOURCE_MANAGER": "resource-manager"
            }
        if pulseaudio:
            self.ROOT_PROPS["PULSE_COOKIE"] = "pulse-cookie"
            self.ROOT_PROPS["PULSE_ID"] = "pulse-id"
            self.ROOT_PROPS["PULSE_SERVER"] = "pulse-server"

    def handshake_complete(self, capabilities):
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
            self.send(["server-settings", {"xsettings-blob": blob}])

    def _handle_root_prop_changed(self, obj, prop, value):
        assert prop in self.ROOT_PROPS
        if value is not None:
            self.send(["server-settings",
                       {self.ROOT_PROPS[prop]: value.encode("utf-8")}])


def get_keymap_spec():
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

system_bell = None
try:
    from wimpiggy.lowlevel.bindings import device_bell
    def x11_system_bell(window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        log("system_bell(%s,%s,%s,%s,%s,%s,%s,%s)" % (window, device, percent, pitch, duration, bell_class, bell_id, bell_name))
        device_bell(window, device, bell_class, bell_id, percent, bell_name)
    system_bell = x11_system_bell
except ImportError, e:
    log.error("cannot import device_bell (turning feature off) : %s", e)

class notifications_wrapper:
    def __init__(self):
        import pynotify
        pynotify.init("Xpra")

    def notify(self, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        import pynotify
        n = pynotify.Notification(summary, body)
        n.show()

    def close_callback(self, id):
        pass
