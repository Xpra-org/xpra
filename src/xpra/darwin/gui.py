# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os.path
import gtk.gdk

from xpra.platform.client_extras_base import ClientExtrasBase, CheckMenuItem
from xpra.platform.clipboard_base import DefaultClipboardProtocolHelper
from xpra.platform import get_icon_dir
from xpra.gtk_common.keys import get_gtk_keymap
from wimpiggy.log import Logger
log = Logger()

#for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10

macapp = None
def get_OSXApplication():
    global macapp
    if macapp is None:
        try:
            import gtkosx_application        #@UnresolvedImport
            macapp = gtkosx_application.Application()
        except:
            pass
    return macapp

is_osx_ready = False
def osx_ready():
    global is_osx_ready
    if not is_osx_ready:
        get_OSXApplication().ready()
        is_osx_ready = True

#we have to do this stuff here so we can
#re-use the same instance
macmenubar = None
hidden_window = None
quit_menu_item = None
def setup_menubar(quit_cb):
    global macmenubar, hidden_window, quit_menu_item
    log("setup_menubar(%s)", quit_cb)
    if macmenubar:
        return macmenubar
    macapp = get_OSXApplication()
    assert macapp
    macmenubar = gtk.MenuBar()
    macmenubar.show_all()
    macapp.set_menu_bar(macmenubar)
    return macmenubar


class ClientExtras(ClientExtrasBase):
    def __init__(self, client, opts, conn):
        self.menu_bar = None
        self.macapp = None
        self.last_attention_request_id = -1
        ClientExtrasBase.__init__(self, client, opts, conn)
        self.locate_icon_filename(opts.tray_icon)
        self.setup_macdock()
        try:
            from xpra.darwin.osx_clipboard import OSXClipboardProtocolHelper
            self.setup_clipboard_helper(OSXClipboardProtocolHelper)
        except ImportError, e:
            log.error("OSX clipboard failed to load: %s - using default fallback", e)
            self.setup_clipboard_helper(DefaultClipboardProtocolHelper)

    def locate_icon_filename(self, opts_tray_icon):
        # ensure icon_filename points to a valid file (or None)
        self.icon_filename = None
        if opts_tray_icon and os.path.exists(opts_tray_icon):
            self.icon_filename = opts_tray_icon
        else:
            #try to find the default icon:
            x = os.path.join(self.get_data_dir(), "xpra", "icons", "xpra.png")
            if os.path.exists(x):
                self.icon_filename = x
        log("darwin client extras using icon_filename=%s", self.icon_filename)

    def cleanup(self):
        ClientExtrasBase.cleanup(self)
        self.remove_all_menus()

    def remove_all_menus(self):
        if self.menu_bar:
            for x in self.menu_bar.get_children():
                self.menu_bar.remove(x)
                x.hide()
        self.info_menu        = None
        self.features_menu    = None
        self.encodings_menu   = None
        self.quality_menu     = None
        self.actions_menu     = None
        if self.macapp:
            self.macapp.sync_menubar()

    def set_tooltip(self, text=None):
        pass        #label cannot be set on the dock icon?

    def set_blinking(self, on):
        if on:
            if self.last_attention_request_id<0:
                self.last_attention_request_id = self.macapp.attention_request(INFO_REQUEST)
        else:
            if self.last_attention_request_id>=0:
                self.macapp.cancel_attention_request(self.last_attention_request_id)
                self.last_attention_request_id = -1

    def set_icon(self, basefilename):
        if not self.macapp:
            return
        with_ext = "%s.png" % basefilename
        icon_dir = get_icon_dir()
        filename = os.path.join(icon_dir, with_ext)
        if not os.path.exists(filename):
            log.error("could not find icon '%s' in osx icon dir: %s", with_ext, icon_dir)
            return
        pixbuf = gtk.gdk.pixbuf_new_from_file(filename)
        self.macapp.set_dock_icon_pixbuf(pixbuf)

    def setup_macdock(self):
        log.debug("setup_macdock()")
        self.macapp = get_OSXApplication()
        try:
            #setup the menu:
            self.menu_bar = setup_menubar(self.quit)
            #remove all existing sub-menus:
            self.remove_all_menus()

            def make_menu(name, submenu):
                item = gtk.MenuItem(name)
                item.set_submenu(submenu)
                item.show_all()
                self.menu_bar.add(item)
                return submenu
            self.info_menu        = make_menu("Info", gtk.Menu())
            self.features_menu    = make_menu("Features", gtk.Menu())
            self.encodings_menu   = make_menu("Encodings", self.make_encodingssubmenu(False))
            if (self.client.speaker_allowed and len(self.client.speaker_codecs)>0) or \
                (self.client.microphone_allowed and len(self.client.microphone_codecs)>0):
                self.sound_menu       = make_menu("Sound", gtk.Menu())
            self.quality_menu     = make_menu("Min Quality", self.make_qualitysubmenu())
            self.speed_menu       = make_menu("Speed", self.make_speedsubmenu())
            self.actions_menu     = make_menu("Actions", gtk.Menu())
            def reset_encodings(*args):
                self.reset_encoding_options(self.encodings_menu)
            self.client.connect("handshake-complete", reset_encodings)

            #info
            self.info_menu.add(self.make_aboutmenuitem())
            self.info_menu.add(self.make_sessioninfomenuitem())
            #features
            self.features_menu.add(self.make_bellmenuitem())
            self.features_menu.add(self.make_cursorsmenuitem())
            self.features_menu.add(self.make_notificationsmenuitem())
            if not self.client.readonly:
                self.features_menu.add(self.make_layoutsmenuitem())
            #sound:
            if self.client.speaker_allowed and len(self.client.speaker_codecs)>0:
                self.sound_menu.add(self.make_speakermenuitem())
            if self.client.microphone_allowed and len(self.client.microphone_codecs)>0:
                self.sound_menu.add(self.make_microphonemenuitem())
            #actions:
            self.actions_menu.add(self.make_refreshmenuitem())
            self.actions_menu.add(self.make_raisewindowsmenuitem())

            self.menu_bar.show_all()
            self.macapp.sync_menubar()

            #dock menu
            self.dock_menu = gtk.Menu()
            self.disconnect_dock_item = gtk.MenuItem("Disconnect")
            self.disconnect_dock_item.connect("activate", self.quit)
            self.dock_menu.add(self.disconnect_dock_item)
            self.dock_menu.show_all()
            self.macapp.set_dock_menu(self.dock_menu)
            if self.icon_filename:
                log("setup_macdock() loading icon from %s", self.icon_filename)
                pixbuf = gtk.gdk.pixbuf_new_from_file(self.icon_filename)
                self.macapp.set_dock_icon_pixbuf(pixbuf)

            self.macapp.connect("NSApplicationBlockTermination", self.quit)
            def dock_ready(*args):
                log.debug("dock_ready()")
                osx_ready()
            self.client.connect("handshake-complete", dock_ready)
        except Exception, e:
            log.error("failed to create dock: %s", e, exc_info=True)

    def make_speakermenuitem(self):
        speaker = CheckMenuItem("Speaker", "Forward sound output from the server")
        def speaker_toggled(*args):
            if speaker.active:
                self.spk_on()
            else:
                self.spk_off()
        def set_speaker(*args):
            speaker.set_active(self.client.speaker_enabled)
            speaker.connect('toggled', speaker_toggled)
        self.client.connect("handshake-complete", set_speaker)
        return speaker

    def make_microphonemenuitem(self):
        microphone = CheckMenuItem("Microphone", "Forward sound input to the server")
        def microphone_toggled(*args):
            if microphone.active:
                self.mic_on()
            else:
                self.mic_off()
        def set_microphone(*args):
            microphone.set_active(self.client.microphone_enabled)
            microphone.connect('toggled', microphone_toggled)
        self.client.connect("handshake-complete", set_microphone)
        return microphone

    def set_speedmenu(self, *args):
        for x in self.speed_menu.get_children():
            if isinstance(x, gtk.CheckMenuItem):
                x.set_sensitive(self.client.encoding=="x264")

    def set_qualitymenu(self, *args):
        vq = not self.client.mmap_enabled and self.client.encoding in ("jpeg", "webp", "x264")
        if not vq:
            self.quality_menu.hide()
        else:
            self.quality_menu.show()
        self.quality_menu.set_sensitive(vq)
        for i in self.quality_menu.get_children():
            i.set_sensitive(vq)

    def can_notify(self):
        return  False

    def show_notify(self, dbus_id, nid, app_name, replaces_id, app_icon, summary, body, expire_timeout):
        pass

    def system_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        import Carbon.Snd           #@UnresolvedImport
        Carbon.Snd.SysBeep(1)

    def get_gtk_keymap(self):
        return  get_gtk_keymap()

    def get_data_dir(self):
        return  os.environ.get("XDG_DATA_DIRS", os.getcwd())
