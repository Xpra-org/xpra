# This file is part of Parti.
# Copyright (C) 2011 Antoine Martin <antoine@nagafix.co.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from wimpiggy.log import Logger
log = Logger()


def grok_modifier_map(display_source):
    modifier_map = {
        "shift": 1 << 0,
        "lock": 1 << 1,
        "control": 1 << 2,
        "mod1": 1 << 3,
        "mod2": 1 << 4,
        "mod3": 1 << 5,
        "mod4": 1 << 6,
        "mod5": 1 << 7,
        "scroll": 0,
        "num": 0,
        "meta": 1 << 3,
        "super": 0,
        "hyper": 0,
        "alt": 0,
        }
    modifier_map["nuisance"] = (modifier_map["lock"]
                                | modifier_map["scroll"]
                                | modifier_map["num"])
    return modifier_map

def get_keymap_spec():
    return None,None,None


xpra_icon_filename = None
if "XDG_DATA_DIRS" in os.environ:
    filename = os.path.join(os.environ["XDG_DATA_DIRS"], "icons", "xpra.png")
    if filename and os.path.exists(filename):
        log.debug("found xpra icon: %s", filename)
        xpra_icon_filename = filename


class ClipboardProtocolHelper(object):
    def __init__(self, send_packet_cb):
        self.send = send_packet_cb

    def send_all_tokens(self):
        pass

    def process_clipboard_packet(self, packet):
        packet_type = packet[0]
        if packet_type == "clipboard_request":
            (_, request_id, selection, _) = packet
            self.send(["clipboard-contents-none", request_id, selection])


class ClientExtras(object):
    def __init__(self, send_packet_cb, pulseaudio, opts):
        self.send = send_packet_cb
        self.growl_notifier = None
        try:
            import Growl        #@UnresolvedImport
            self.growl_notifier = Growl.GrowlNotifier("Xpra", ["highlight"])
            self.growl_notifier.register()
            log.error("using growl for notications: %s", self.growl_notifier)
        except Exception, e:
            log.error("failed to load Growl: %s, notifications will not be shown", e)
        # ensure icon_filename points to a valid file (or None)
        self.icon_filename = xpra_icon_filename
        if opts.dock_icon and os.path.exists(opts.dock_icon):
            self.icon_filename = opts.dock_icon
        elif self.icon_filename and not os.path.exists(self.icon_filename):
            self.icon_filename = None
        log.info("darwin client extras using icon_filename=%s", self.icon_filename)
        self.setup_macdock()
    
    def setup_macdock(self):
        log.debug("setup_macdock()")
        self.mac_dock = None
        try:
            import gtk_osxapplication		#@UnresolvedImport
            self.macapp = gtk_osxapplication.OSXApplication()
            if self.icon_filename:
                log.debug("setup_macdock() loading icon from %s", self.icon_filename)
                pixbuf = gtk.gdk.pixbuf_new_from_file(self.icon_filename)
                self.macapp.set_dock_icon_pixbuf(pixbuf)
            self.macapp.connect("NSApplicationBlockTermination", gtk.main_quit)
            self.macapp.ready()
        except Exception, e:
            log.debug("failed to create dock: %s", e)

    def handshake_complete(self):
        pass

    def can_notify(self):
        return  self.growl_notifier is not None

    def show_notify(self, dbus_id, id, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        if not self.growl_notifier:
            return
        if self.icon_filename:
            import Growl.Image  #@UnresolvedImport
            icon = Growl.Image.imageFromPath(self.icon_filename)
        else:
            icon = None
        sticky = expire_timeout>30
        self.growl_notifier.notify('highlight', summary, body, icon, sticky)

    def close_notify(self, id):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import Carbon.Snd           #@UnresolvedImport
        Carbon.Snd.SysBeep(1)
