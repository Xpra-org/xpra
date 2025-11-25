# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.client.base.stub import StubClientMixin
from xpra.client.gui.keyboard_helper import KeyboardHelper
from xpra.keyboard.common import KeyEvent, DELAY_KEYBOARD_DATA
from xpra.util.objects import typedict
from xpra.common import noop
from xpra.log import Logger

log = Logger("keyboard")


def noauto(val: str | Sequence | None) -> str | Sequence | None:
    default = [] if isinstance(val, Sequence) else None
    if not val:
        return default
    if str(val).lower() == "auto":
        return default
    return val


class KeyboardClient(StubClientMixin):
    """
    Utility mixin for clients that handle keyboard input
    """
    PREFIX = "keyboard"

    def __init__(self):
        self.keyboard_enabled = True
        self.keyboard_helper_class: type = KeyboardHelper
        self.keyboard_helper = None
        self.keyboard_grabbed: bool = False
        self.keyboard_sync: bool = False
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.server_keyboard: bool = True
        self.kh_warning: bool = False

    def init_ui(self, opts) -> None:
        send_keyboard = noop
        if not self.readonly:
            def do_send_keyboard(*parts):
                self.after_handshake(self.send, *parts)

            send_keyboard = do_send_keyboard
        try:
            kwargs = dict(
                (x, noauto(getattr(opts, "keyboard_%s" % x))) for x in (
                    "backend", "model", "layout", "layouts", "variant", "variants", "options",
                )
            )
            self.keyboard_helper = self.keyboard_helper_class(send_keyboard, opts.keyboard_sync,
                                                              opts.shortcut_modifiers,
                                                              opts.key_shortcut,
                                                              opts.keyboard_raw, **kwargs)
            if DELAY_KEYBOARD_DATA and not self.readonly:
                self.after_handshake(self.keyboard_helper.send_keymap)
        except ImportError as e:
            log("error instantiating %s", self.keyboard_helper_class, exc_info=True)
            log.warn(f"Warning: no keyboard support, {e}")

    def cleanup(self) -> None:
        kh = self.keyboard_helper
        if kh:
            self.keyboard_helper = None
            kh.cleanup()

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {KeyboardClient.PREFIX: self.get_keyboard_caps()}

    def get_caps(self) -> dict[str, Any]:
        # return {KeyboardClient.PREFIX: caps}
        return self.get_keyboard_caps()

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_keyboard = c.boolget("keyboard", True)
        if not self.server_keyboard and self.keyboard_helper:
            # swallow packets:
            self.keyboard_helper.send = noop
        try:
            from xpra import keyboard
            assert keyboard
        except ImportError:
            log.warn("Warning: keyboard module is missing")
            self.keyboard_enabled = False
            return True
        return True

    def process_ui_capabilities(self, caps: typedict) -> None:
        log("process_ui_capabilities()")
        if self.keyboard_helper:
            modifier_keycodes = caps.dictget("modifier_keycodes", {})
            if modifier_keycodes:
                self.keyboard_helper.set_modifier_mappings(modifier_keycodes)
        self.key_repeat_delay, self.key_repeat_interval = caps.intpair("key_repeat", (-1, -1))

    def get_keyboard_caps(self) -> dict[str, Any]:
        caps = {}
        kh = self.keyboard_helper
        if self.readonly or not kh:
            # don't bother sending keyboard info, as it won't be used
            caps["keyboard"] = False
        else:
            caps["keyboard"] = True
            caps["ibus"] = True
            caps["modifiers"] = self.get_current_modifiers()
            skip = ("keycodes", "x11_keycodes") if DELAY_KEYBOARD_DATA else ()
            caps["keymap"] = kh.get_keymap_properties(skip)
            # show the user a summary of what we have detected:
            self.keyboard_helper.log_keyboard_info()
            delay_ms, interval_ms = kh.key_repeat_delay, kh.key_repeat_interval
            if delay_ms > 0 and interval_ms > 0:
                caps["key_repeat"] = (delay_ms, interval_ms)
            else:
                # cannot do keyboard_sync without a key repeat value!
                # (maybe we could just choose one?)
                kh.keyboard_sync = False
            caps["keyboard_sync"] = kh.sync
        log("keyboard capabilities: %s", caps)
        return caps

    def next_keyboard_layout(self, update_platform_layout) -> None:
        if self.keyboard_helper:
            self.keyboard_helper.next_layout(update_platform_layout)

    def window_keyboard_layout_changed(self, window=None) -> None:
        # win32 can change the keyboard mapping per window...
        log("window_keyboard_layout_changed(%s)", window)
        if self.keyboard_helper:
            self.keyboard_helper.keymap_changed()

    def handle_key_action(self, window, key_event: KeyEvent) -> bool:
        kh = self.keyboard_helper
        if not kh:
            return False
        wid = self._window_to_id[window]
        log(f"handle_key_action({window}, {key_event}) wid={wid:#x}")
        if kh.key_handled_as_shortcut(window, key_event.keyname, key_event.modifiers, key_event.pressed):
            return False
        if self.readonly:
            return False
        kh.process_key_event(wid, key_event)
        return False

    def mask_to_names(self, mask) -> list[str]:
        if self.keyboard_helper is None:
            return []
        return self.keyboard_helper.mask_to_names(int(mask))
