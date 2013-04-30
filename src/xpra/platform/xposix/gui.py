# This file is part of Xpra.
# Copyright (C) 2010 Nathaniel Smith <njs@pobox.com>
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()


try:
    from xpra.x11.gtk_x11.error import trap, XError
    from xpra.x11.lowlevel.bindings import device_bell      #@UnresolvedImport
except:
    device_bell = None

def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
    global device_bell
    if device_bell is None:
        return False
    try:
        trap.call_synced(device_bell, window, device, bell_class, bell_id, percent, bell_name)
        return  True
    except XError, e:
        log.error("error using device_bell: %s, switching native X11 bell support off", e)
        device_bell = None
        return False


class ClientExtras(object):
    def __init__(self, client, opts, conn):
        self.setup_xprops()
        self.setup_x11_bell()
        self.setup_pa_audio_tagging()

    def setup_pa_audio_tagging(self):
        try:
            from xpra.sound.pulseaudio_util import add_audio_tagging_env
            add_audio_tagging_env(self.get_tray_icon_filename(None))
        except Exception, e:
            log("failed to set pulseaudio audio tagging: %s", e)

    def setup_xprops(self):
        self.ROOT_PROPS = {
            "RESOURCE_MANAGER": "resource-manager"
            }
        def setup_xprop_xsettings(client):
            log.debug("setup_xprop_xsettings(%s)", client)
            try:
                from xpra.x11.xsettings import XSettingsWatcher
                from xpra.x11.xroot_props import XRootPropWatcher
                self._xsettings_watcher = XSettingsWatcher()
                self._xsettings_watcher.connect("xsettings-changed", self._handle_xsettings_changed)
                self._handle_xsettings_changed()
                self._root_props_watcher = XRootPropWatcher(self.ROOT_PROPS.keys())
                self._root_props_watcher.connect("root-prop-changed", self._handle_root_prop_changed)
                self._root_props_watcher.notify_all()
            except ImportError, e:
                log.error("failed to load X11 properties/settings bindings: %s - root window properties will not be propagated", e)
        self.client.connect("handshake-complete", setup_xprop_xsettings)

    def _handle_xsettings_changed(self, *args):
        try:
            blob = self._xsettings_watcher.get_settings_blob()
        except:
            log.error("failed to get XSETTINGS", exc_info=True)
            return
        log("xsettings_changed new value=%s", blob)
        if blob is not None:
            self.client.send("server-settings", {"xsettings-blob": blob})

    def _handle_root_prop_changed(self, obj, prop, value):
        log("root_prop_changed: %s=%s", prop, value)
        assert prop in self.ROOT_PROPS
        if value is not None and self.client.xsettings_tuple:
            self.client.send("server-settings", {self.ROOT_PROPS[prop]: value.encode("utf-8")})
