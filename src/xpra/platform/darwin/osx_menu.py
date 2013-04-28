# This file is part of Xpra.
# Copyright (C) 2011-2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.gtk_common.gobject_compat import import_gtk
from xpra.gtk_common.gtk_util import CheckMenuItem
gtk = import_gtk()

from xpra.log import Logger
log = Logger()

#for attention_request:
CRITICAL_REQUEST = 0
INFO_REQUEST = 10


class OSXMenuHelper(object):
    """
    we have to do this stuff here so we can
    re-use the same instance
    """

    def __init__(self, client):
        self.client = client
        self.menu_bar = None
        self.hidden_window = None
        self.quit_menu_item = None

    def quit(self):
        self.client.quit(0)

    def build(self):
        if self.menu_bar is None:
            self.build_menu_bar()
        return self.menu_bar

    def rebuild(self):
        if self.menu_bar:
            self.remove_all_menus()
            self.menu_bar = None
        self.build()

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
        #if self.macapp:
        #    self.macapp.sync_menubar()

    def build_menu_bar(self):
        self.menu_bar = gtk.MenuBar()
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
