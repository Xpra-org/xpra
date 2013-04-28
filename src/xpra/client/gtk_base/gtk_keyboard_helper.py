# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010-2013 Antoine Martin <antoine@devloop.org.uk>
# Copyright (C) 2008, 2010 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.log import Logger
log = Logger()

from xpra.client.keyboard_helper import KeyboardHelper, nn
from xpra.gtk_common.gobject_compat import import_gdk, import_gobject
from xpra.gtk_common.keymap import get_gtk_keymap
gdk = import_gdk()
gobject = import_gobject()


class GTKKeyboardHelper(KeyboardHelper):

    def __init__(self, net_send, keyboard_sync, key_shortcuts, send_layout, send_keymap):
        self.send_layout = send_layout
        self.send_keymap = send_keymap
        KeyboardHelper.__init__(self, net_send, keyboard_sync, key_shortcuts)
        self._keymap_changing = False
        try:
            self._keymap = gdk.keymap_get_default()
        except:
            self._keymap = None
        self._do_keys_changed()
        if self._keymap:
            self._keymap.connect("keys-changed", self._keys_changed)

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
            self.keyboard.update_modifier_map(gdk.display_get_default(), self.xkbmap_mod_meanings)
        except:
            pass
        log.debug("do_keys_changed() modifier_map=%s" % self.keyboard.modifier_map)
        if sendkeymap:
            if self.xkbmap_layout:
                self.send_layout()
            self.send_keymap()

    def get_full_keymap(self):
        return  get_gtk_keymap()

    def parse_key_event(self, wid, event, pressed):
        modifiers = self.mask_to_names(event.state)
        keyname = nn(gdk.keyval_name(event.keyval))
        keyval = nn(event.keyval)
        keycode = event.hardware_keycode
        group = event.group
        string = nn(event.string)
        return wid, keyname, pressed, modifiers, keyval, string, keycode, group
