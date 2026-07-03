# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any
from collections.abc import Sequence

from xpra.client.base import features
from xpra.client.base.stub import StubClientSubsystem
from xpra.client.gui.keyboard_helper import KeyboardHelper
from xpra.keyboard.common import KeyEvent, DELAY_KEYBOARD_DATA
from xpra.util.objects import typedict
from xpra.common import noop
from xpra.os_util import WIN32
from xpra.log import Logger

log = Logger("keyboard")


def noauto(val: str | Sequence | None) -> str | Sequence | None:
    default = [] if isinstance(val, Sequence) else None
    if not val:
        return default
    if str(val).lower() == "auto":
        return default
    return val


class KeyboardClient(StubClientSubsystem):
    """
    Utility mixin for clients that handle keyboard input
    """
    PREFIX = "keyboard"

    def __init__(self, client=None):
        StubClientSubsystem.__init__(self, client)
        self.enabled = True
        self.helper_class: type = KeyboardHelper
        self.helper = None
        self.grabbed: bool = False
        self.sync: bool = False
        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.server_enabled: bool = True
        self.warning: bool = False
        # win32 global low-level keyboard hook:
        self._win32_keyboard_hook = None

    def init_ui(self, opts) -> None:
        send_keyboard = noop
        if not self.client.readonly:
            def do_send_keyboard(*parts):
                log("do_send_keyboard%s", parts)
                self.client.after_handshake(self.send, *parts)

            send_keyboard = do_send_keyboard
        try:
            kwargs = dict(
                (x, noauto(getattr(opts, "keyboard_%s" % x))) for x in (
                    "backend", "model", "layout", "layouts", "variant", "variants", "options",
                )
            )
            self.sync = opts.keyboard_sync
            self.helper = self.helper_class(send_keyboard, self.sync,
                                            opts.shortcut_modifiers,
                                            opts.key_shortcut,
                                            opts.keyboard_raw, **kwargs)
            if DELAY_KEYBOARD_DATA and not self.client.readonly:
                self.client.after_handshake(self.helper.send_config)
        except ImportError as e:
            log("error instantiating %s", self.helper_class, exc_info=True)
            log.warn(f"Warning: no keyboard support, {e}")
        # only meaningful on macOS, but harmless to set unconditionally:
        if self.helper and self.helper.keyboard:
            log("%s.swap_keys=%s", self.helper.keyboard, opts.swap_keys)
            self.helper.keyboard.swap_keys = opts.swap_keys

    def run(self) -> None:
        if WIN32:
            from xpra.platform.win32.gui import FORWARD_WINDOWS_KEY
            if FORWARD_WINDOWS_KEY and features.window:
                from xpra.platform.win32.keyboard_hook import Win32KeyboardHookWatcher
                self._win32_keyboard_hook = Win32KeyboardHookWatcher(self)
                self._win32_keyboard_hook.setup()

    def cleanup(self) -> None:
        if kh := self.helper:
            self.helper = None
            kh.cleanup()
        if wkh := self._win32_keyboard_hook:
            self._win32_keyboard_hook = None
            wkh.cleanup()

    def get_info(self) -> dict[str, dict[str, Any]]:
        return {KeyboardClient.PREFIX: self.get_keyboard_caps()}

    def get_caps(self) -> dict[str, Any]:
        # return {KeyboardClient.PREFIX: caps}
        return self.get_keyboard_caps()

    def parse_server_capabilities(self, c: typedict) -> bool:
        self.server_enabled = c.boolget("keyboard", True)
        if not self.server_enabled and self.helper:
            # swallow packets:
            self.helper.send = noop
        try:
            from xpra import keyboard
            if not keyboard:
                # cythonized code can bind None for missing imports
                raise ImportError("xpra.keyboard")
        except ImportError:
            log.warn("Warning: keyboard module is missing")
            self.enabled = False
            return True
        if self.helper:
            modifier_keycodes = c.dictget("modifier_keycodes")
            if modifier_keycodes:
                self.helper.set_modifier_mappings(modifier_keycodes)
        self.key_repeat_delay, self.key_repeat_interval = c.intpair("key_repeat", (-1, -1))
        return True

    def get_keyboard_caps(self) -> dict[str, Any]:
        caps = {}
        kh = self.helper
        if self.client.readonly or not kh:
            # don't bother sending keyboard info, as it won't be used
            caps["keyboard"] = False
        else:
            caps["keyboard"] = True
            caps["ibus"] = True
            caps["modifiers"] = self.get_current_modifiers()
            delay_ms, interval_ms = kh.key_repeat_delay, kh.key_repeat_interval
            if delay_ms <= 0 or interval_ms <= 0:
                # cannot do keyboard sync without a key repeat value
                self.sync = False
            kh.sync = self.sync
            skip = ("keycodes", "x11_keycodes") if DELAY_KEYBOARD_DATA else ()
            caps["keymap"] = kh.get_keymap_properties(skip)
            # show the user a summary of what we have detected:
            self.helper.log_keyboard_info()
            if delay_ms > 0 and interval_ms > 0:
                caps["key_repeat"] = (delay_ms, interval_ms)
            caps["keyboard_sync"] = self.sync
        log("keyboard capabilities: %s", caps)
        return caps

    def next_keyboard_layout(self, update_platform_layout) -> None:
        if self.helper:
            self.helper.next_layout(update_platform_layout)

    def window_keyboard_layout_changed(self, window=None) -> None:
        # win32 can change the keyboard mapping per window...
        log("window_keyboard_layout_changed(%s)", window)
        if self.helper:
            self.helper.keymap_changed()

    def handle_key_action(self, window, key_event: KeyEvent) -> bool:
        kh = self.helper
        if not kh:
            return False
        # the window registry is owned by the `window` subsystem:
        window_sub = self.get_subsystem("window")
        wid = window_sub._window_to_id[window]
        log(f"handle_key_action({window}, {key_event}) wid={wid:#x}")
        if kh.key_handled_as_shortcut(window, key_event.keyname, key_event.modifiers, key_event.pressed):
            return False
        if self.client.readonly:
            return False
        kh.process_key_event(wid, key_event)
        return False

    def mask_to_names(self, mask) -> list[str]:
        if self.helper is None:
            return []
        return self.helper.mask_to_names(int(mask))

    def get_current_modifiers(self) -> Sequence[str]:
        # delegate to the client for now, since querying the current modifiers
        # requires toolkit-specific access to the pointer / root window:
        return self.client.get_current_modifiers()
