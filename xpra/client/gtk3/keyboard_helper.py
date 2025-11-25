# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.client.gui.keyboard_helper import KeyboardHelper, KEYCODE_DEF
from xpra.gtk.keymap import get_gtk_keymap, get_default_keymap
from xpra.os_util import gi_import
from xpra.util.system import is_X11
from xpra.log import Logger

log = Logger("keyboard", "gtk")

Gdk = gi_import("Gdk")
GLib = gi_import("GLib")


class GTKKeyboardHelper(KeyboardHelper):

    def __init__(self, *args, **kwargs):
        KeyboardHelper.__init__(self, *args, **kwargs)
        # used for delaying the sending of keymap changes
        # (as we may be getting dozens of such events at a time)
        self._keymap_changing = False
        self._keymap_change_handler_id = None
        self._keymap = get_default_keymap()
        self.update()
        if self._keymap:
            self._keymap_change_handler_id = self._keymap.connect("keys-changed", self.keymap_changed)

    def next_layout(self, update_platform_layout) -> None:
        log(f"next_layout(update_platform_layout={update_platform_layout})")
        if self.layout_option not in self.layouts_option:
            log("no layout change; use --keyboard-layout/--keyboard-layouts to specify the layouts order")
            return
        try:
            layout_index = self.layouts_option.index(self.layout_option)
        except ValueError as e:
            log.warn("failed to find layout %s among layouts: %s", self.layout_option, e)
            return
        layout_index = (layout_index + 1) % len(self.layouts_option)
        self.layout_option = self.layouts_option[layout_index]
        log.info("calling keymap_changed to apply %s layout", self.layout_option)
        self.keymap_changed()
        if update_platform_layout:
            log("updating the platform layout to %s", self.layout_option)
            self.set_platform_layout(self.layout_option)

    def keymap_changed(self, *args) -> None:
        log("keymap_changed%s", args)
        if self._keymap_change_handler_id:
            self._keymap.disconnect(self._keymap_change_handler_id)
            self._keymap_change_handler_id = None
        self._keymap = get_default_keymap()
        if self._keymap_changing:
            # timer is already due
            return
        self._keymap_changing = True

        def do_keys_changed() -> None:
            # re-register the change handler:
            self._keymap_change_handler_id = self._keymap.connect("keys-changed", self.keymap_changed)
            self._keymap_changing = False
            if self.locked:
                # automatic changes not allowed!
                log.info("ignoring keymap change: layout is locked to '%s'", self.layout_str())
                return
            if self.update() and self.layout:
                log.info("keymap has been changed to '%s'", self.layout_str())
                log.info(" sending updated mappings to the server")
                if self.layout:
                    self.send_layout()
                self.send_keymap(False)

        GLib.timeout_add(500, do_keys_changed)

    def update(self) -> bool:
        old_hash = self.hash
        super().update()
        if is_X11():
            with log.trap_error("Error querying modifier map"):
                self.keyboard.update_modifier_map(self.mod_meanings)
        log("update() modifier_map=%s, old hash=%s, new hash=%s", self.keyboard.modifier_map, old_hash, self.hash)
        return old_hash != self.hash

    def get_full_keymap(self) -> Sequence[KEYCODE_DEF]:
        return get_gtk_keymap()

    def cleanup(self) -> None:
        super().cleanup()
        if self._keymap_change_handler_id:
            try:
                self._keymap.disconnect(self._keymap_change_handler_id)
                self._keymap_change_handler_id = None
            except Exception as e:
                log.warn("failed to disconnect keymap change handler: %s", e)


def main() -> None:
    # use gtk as display source:
    # pylint: disable=import-outside-toplevel
    from xpra.common import noop
    from xpra.gtk.util import init_display_source
    from xpra.util.str_fn import print_nested_dict
    from xpra.platform import program_context
    with program_context("GTK-Keyboard", "GTK Keyboard"):
        init_display_source(False)
        x = GTKKeyboardHelper(noop)
        x.query_xkbmap()
        print_nested_dict(x.get_keymap_properties())


if __name__ == "__main__":
    main()
