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

