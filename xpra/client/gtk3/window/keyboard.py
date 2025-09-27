# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import gi_import
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.util.env import first_time, envbool
from xpra.client.gtk3.window.stub_window import GtkStubWindow
from xpra.gtk.keymap import KEY_TRANSLATIONS
from xpra.keyboard.common import KeyEvent
from xpra.log import Logger

Gdk = gi_import("Gdk")

log = Logger("window", "keyboard")

UNICODE_KEYNAMES = envbool("XPRA_UNICODE_KEYNAMES", False)


class KeyboardWindow(GtkStubWindow):

    def init_window(self, client, metadata: typedict, client_props: typedict) -> None:
        self.connect("key-press-event", self.handle_key_press_event)
        self.connect("key-release-event", self.handle_key_release_event)

    def get_window_event_mask(self) -> Gdk.EventMask:
        return Gdk.EventMask.KEY_PRESS_MASK | Gdk.EventMask.KEY_RELEASE_MASK

    def next_keyboard_layout(self, update_platform_layout) -> None:
        self._client.next_keyboard_layout(update_platform_layout)

    def keyboard_layout_changed(self, *args) -> None:
        # used by win32 hooks to tell us about keyboard layout changes for this window
        log("keyboard_layout_changed%s", args)
        self._client.window_keyboard_layout_changed(self)

    def parse_key_event(self, event, pressed: bool) -> KeyEvent:
        keyval = event.keyval
        keycode = event.hardware_keycode
        keyname = Gdk.keyval_name(keyval) or ""
        keyname = KEY_TRANSLATIONS.get((keyname, keyval, keycode), keyname)
        if keyname.startswith("U+") and not UNICODE_KEYNAMES:
            # workaround for MS Windows, try harder to find a valid key
            # see ticket #3417
            keymap = Gdk.Keymap.get_default()
            r = keymap.get_entries_for_keycode(event.hardware_keycode)
            if r[0]:
                for kc in r[2]:
                    keyname = Gdk.keyval_name(kc)
                    if not keyname.startswith("U+"):
                        break
        key_event = KeyEvent()
        key_event.modifiers = self._client.mask_to_names(event.state)
        key_event.keyname = keyname
        key_event.keyval = keyval or 0
        key_event.keycode = keycode
        key_event.group = event.group
        key_event.pressed = pressed
        key_event.string = ""
        try:
            codepoint = Gdk.keyval_to_unicode(keyval)
            key_event.string = chr(codepoint)
        except ValueError as e:
            log(f"failed to parse unicode string value of {event}", exc_info=True)
            try:
                key_event.string = event.string or ""
            except UnicodeDecodeError as ve:
                if first_time(f"key-{keycode}-{keyname}"):
                    log("parse_key_event(%s, %s)", event, pressed, exc_info=True)
                    log.warn("Warning: failed to parse string for key")
                    log.warn(f" {keyname=}, {keycode=}")
                    log.warn(f" {keyval=}, group={event.group}")
                    log.warn(" modifiers=%s", csv(key_event.modifiers))
                    log.warn(f" {e}")
                    log.warn(f" {ve}")
        log("parse_key_event(%s, %s)=%s", event, pressed, key_event)
        return key_event

    def handle_key_press_event(self, _window, event) -> bool:
        key_event = self.parse_key_event(event, True)
        self._client.handle_key_action(self, key_event)
        return True

    def handle_key_release_event(self, _window, event) -> bool:
        key_event = self.parse_key_event(event, False)
        self._client.handle_key_action(self, key_event)
        return True
