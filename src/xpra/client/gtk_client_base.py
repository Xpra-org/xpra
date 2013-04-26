# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from wimpiggy.gobject_compat import import_gobject, import_gtk, import_gdk
gobject = import_gobject()
gtk = import_gtk()
gdk = import_gdk()

from wimpiggy.util import (gtk_main_quit_really,
                           gtk_main_quit_on_fatal_exceptions_enable)

from wimpiggy.log import Logger
log = Logger()

from xpra.gtk_common.cursor_names import cursor_names
from xpra.client.ui_client_base import UIXpraClient
from xpra.gtk_common.gtk_util import add_gtk_version_info


class GTKXpraClient(UIXpraClient, gobject.GObject):

    def __init__(self, conn, opts):
        gobject.GObject.__init__(self)
        UIXpraClient.__init__(self, conn, opts)

    def init_keyboard(self, keyboard_sync, key_shortcuts):
        self._keymap_changing = False
        try:
            self._keymap = gdk.keymap_get_default()
        except:
            self._keymap = None
        self._do_keys_changed()
        if self._keymap:
            self._keymap.connect("keys-changed", self._keys_changed)
        UIXpraClient.init_keyboard(self, keyboard_sync, key_shortcuts)

    def get_root_size(self):
        raise Exception("override me!")

    def set_windows_cursor(self, gtkwindows, new_cursor):
        raise Exception("override me!")

    def client_type(self):
        #overriden in subclasses!
        return "Gtk"


    def timeout_add(self, *args):
        return gobject.timeout_add(*args)

    def idle_add(self, *args):
        return gobject.idle_add(*args)

    def source_remove(self, *args):
        return gobject.source_remove(*args)


    def run(self):
        gtk_main_quit_on_fatal_exceptions_enable()
        gtk.main()
        log("XpraClient.run() main loop ended, returning exit_code=%s", self.exit_code)
        return  self.exit_code

    def quit(self, exit_code=0):
        log("XpraClient.quit(%s) current exit_code=%s", exit_code, self.exit_code)
        if self.exit_code is None:
            self.exit_code = exit_code
        if gtk.main_level()>0:
            #if for some reason cleanup() hangs, maybe this will fire...
            gobject.timeout_add(4*1000, gtk_main_quit_really)
            #try harder!:
            gobject.timeout_add(5*1000, os._exit, 1)
        self.cleanup()
        if gtk.main_level()>0:
            log("XpraClient.quit(%s) main loop at level %s, calling gtk quit via timeout", exit_code, gtk.main_level())
            gobject.timeout_add(500, gtk_main_quit_really)


    def _keys_changed(self, *args):
        log.debug("keys_changed")
        self._keymap = gdk.keymap_get_default()
        if not self._keymap_changing:
            self._keymap_changing = True
            gobject.timeout_add(500, self._do_keys_changed, True)

    def _do_keys_changed(self, sendkeymap=False):
        self._keymap_changing = False
        self.query_xkbmap()
        try:
            self._modifier_map = self._client_extras.grok_modifier_map(gdk.display_get_default(), self.xkbmap_mod_meanings)
        except:
            self._modifier_map = {}
        log.debug("do_keys_changed() modifier_map=%s" % self._modifier_map)
        if sendkeymap and not self.readonly:
            if self.xkbmap_layout:
                self.send_layout()
            self.send_keymap()

    def get_current_modifiers(self):
        modifiers_mask = gdk.get_default_root_window().get_pointer()[-1]
        return self.mask_to_names(modifiers_mask)

    def mask_to_names(self, mask):
        if self._client_extras is None:
            return []
        return self._client_extras.mask_to_names(mask)


    def make_hello(self, challenge_response=None):
        capabilities = UIXpraClient.make_hello(self, challenge_response)
        capabilities["named_cursors"] = len(cursor_names)>0
        add_gtk_version_info(capabilities, gtk)
        return capabilities


    def window_bell(self, window, device, percent, pitch, duration, bell_class, bell_id, bell_name):
        gdkwindow = None
        if window:
            gdkwindow = window.get_window()
        if gdkwindow is None:
            gdkwindow = gdk.get_default_root_window()
        log("window_bell(..) gdkwindow=%s", gdkwindow)
        self._client_extras.system_bell(gdkwindow, device, percent, pitch, duration, bell_class, bell_id, bell_name)


gobject.type_register(GTKXpraClient)
