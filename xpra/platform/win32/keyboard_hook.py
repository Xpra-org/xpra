# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import (
    Structure, POINTER, byref, get_last_error,
    create_string_buffer, c_int, CFUNCTYPE, WinError,
)
from ctypes.wintypes import DWORD, WPARAM, LPARAM, MSG

from xpra.keyboard.common import KeyEvent
from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import (
    GetKeyboardLayoutName, CallNextHookEx, GetKeyState,
    SetWindowsHookExA, GetModuleHandleA, GetMessageA, TranslateMessage, DispatchMessageA,
    UnhookWindowsHookEx,
)
from xpra.platform.win32.gui import POLL_LAYOUT, grablog, keylog
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "events")
GLib = gi_import("GLib")

ALL_KEY_EVENTS: dict[int, str] = {
    win32con.WM_KEYDOWN: "KEYDOWN",
    win32con.WM_SYSKEYDOWN: "SYSKEYDOWN",
    win32con.WM_KEYUP: "KEYUP",
    win32con.WM_SYSKEYUP: "SYSKEYUP",
}

KEY_DOWN_EVENTS = [win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN]


class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("vk_code", DWORD),
        ("scan_code", DWORD),
        ("flags", DWORD),
        ("time", c_int),
    ]

    def toString(self) -> str:
        return f"KBDLLHOOKSTRUCT({self.vk_code}, {self.scan_code}, {self.flags:x}, {self.time})"


def get_keyboard_layout_id() -> int:
    name_buf = create_string_buffer(win32con.KL_NAMELENGTH)
    if not GetKeyboardLayoutName(name_buf):
        return 0
    name_str = name_buf.value.decode("latin1")
    log(f"layout-name={name_str!r}")
    try:
        # win32 API returns a hex string
        return int(name_str, 16)
    except ValueError:
        log.warn("Warning: failed to parse keyboard layout code %r", name_str)
    return 0


def may_handle_key_event(keyboard, scan_code: int, vk_code: int, pressed: bool) -> KeyEvent | None:
    modifier_keycodes = keyboard.modifier_keycodes
    modifier_keys = keyboard.modifier_keys
    keyname = {
        win32con.VK_LWIN: "Super_L",
        win32con.VK_RWIN: "Super_R",
        win32con.VK_TAB: "Tab",
    }.get(vk_code, "")
    if keyname.startswith("Super"):
        keycode = 0
        # find the modifier keycode: (try the exact key we hit first)
        for x in (keyname, "Super_L", "Super_R"):
            keycodes = modifier_keycodes.get(x, [])
            for k in keycodes:
                # only interested in numeric keycodes:
                try:
                    keycode = int(k)
                    break
                except ValueError:
                    pass
            if keycode > 0:
                break
    else:
        keycode = vk_code  # true for non-modifier keys only!
    modifiers: list[str] = []
    for vk, modkeynames in {
        win32con.VK_NUMLOCK: ["Num_Lock"],
        win32con.VK_CAPITAL: ["Caps_Lock"],
        win32con.VK_CONTROL: ["Control_L", "Control_R"],
        win32con.VK_SHIFT: ["Shift_L", "Shift_R"],
    }.items():
        if GetKeyState(vk):
            for modkeyname in modkeynames:
                mod = modifier_keys.get(modkeyname)
                if mod:
                    modifiers.append(mod)
                    break
    grablog("vk_code=%s, scan_code=%s, keyname=%s, keycode=%s, modifiers=%s",
            vk_code, scan_code, keyname, keycode, modifiers)
    if keycode <= 0:
        return None
    key_event = KeyEvent()
    key_event.keyname = keyname
    key_event.pressed = pressed
    key_event.modifiers = modifiers
    key_event.keyval = scan_code
    key_event.keycode = keycode
    key_event.string = ""
    key_event.group = 0
    grablog("detected '%s' key, sending %s", keyname, key_event)
    return key_event


class Win32KeyboardHookWatcher:
    """
    Low-level global keyboard hook + keyboard-layout polling, feeding the
    `keyboard` subsystem.
    """

    def __init__(self, keyboard_client):
        self.keyboard = keyboard_client
        self._keyboard_poll_exit = False
        self._keyboard_hook_id = 0
        self._keyboard_poll_timer: int = 0
        self._keyboard_id: int = get_keyboard_layout_id()

    def setup(self) -> None:
        from xpra.util.thread import start_thread
        start_thread(self.run_keyboard_listener, "keyboard-listener", daemon=True)

    def cleanup(self) -> None:
        self._keyboard_poll_exit = True
        if khid := self._keyboard_hook_id:
            self._keyboard_hook_id = 0
            UnhookWindowsHookEx(khid)
        if kpt := self._keyboard_poll_timer:
            self._keyboard_poll_timer = 0
            GLib.source_remove(kpt)

    def poll_layout(self) -> None:
        self._keyboard_poll_timer = 0
        klid = get_keyboard_layout_id()
        if klid and klid != self._keyboard_id:
            self._keyboard_id = klid
            self.keyboard.window_keyboard_layout_changed()

    def run_keyboard_listener(self) -> None:

        def low_level_keyboard_handler(ncode: int, wparam: int, lparam: int):
            log("WH_KEYBOARD_LL: %s", (ncode, wparam, lparam))
            kh = self.keyboard.helper
            locked = kh.locked if kh else False
            if POLL_LAYOUT and self._keyboard_poll_timer == 0 and not locked:
                self._keyboard_poll_timer = GLib.timeout_add(POLL_LAYOUT, self.poll_layout)
            # docs say we should not process events with ncode < 0:
            if ncode >= 0 and kh and kh.keyboard and lparam:
                try:
                    scan_code = lparam.contents.scan_code
                    vk_code = lparam.contents.vk_code
                    window = self.keyboard.get_subsystem("window")
                    focused = bool(window and window._focused)
                    # the keys we want intercept before the OS:
                    trap = vk_code in (win32con.VK_LWIN, win32con.VK_RWIN, win32con.VK_TAB)
                    key_event_type = ALL_KEY_EVENTS.get(wparam)
                    if self.keyboard.grabbed and focused and trap and key_event_type:
                        pressed = wparam in KEY_DOWN_EVENTS
                        key_event = may_handle_key_event(kh.keyboard, scan_code, vk_code, pressed)
                        if key_event:
                            grablog("grab key, sending %s", key_event)
                            kh.send_key_action(focused, key_event)
                            # swallow this event:
                            return 1
                except Exception as e:
                    keylog("low_level_keyboard_handler(%i, %i, %r)", ncode, wparam, lparam, exc_info=True)
                    keylog.error("Error: low level keyboard hook failed")
                    keylog.estr(e)
            return CallNextHookEx(0, ncode, wparam, lparam)

        # Our low level handler signature.
        CMPFUNC = CFUNCTYPE(c_int, WPARAM, LPARAM, POINTER(KBDLLHOOKSTRUCT))
        # Convert the Python handler into C pointer.
        pointer = CMPFUNC(low_level_keyboard_handler)
        # Hook both key up and key down events for common keys (non-system).
        self._keyboard_hook_id = SetWindowsHookExA(win32con.WH_KEYBOARD_LL, pointer, GetModuleHandleA(None), 0)
        # Register to remove the hook when the interpreter exits:
        keylog("run_keyboard_listener() hook_id=%#x", self._keyboard_hook_id)
        msg = MSG()
        lpmsg = byref(msg)  # NOSONAR
        while not self._keyboard_poll_exit:
            ret = GetMessageA(lpmsg, 0, 0, 0)
            keylog("keyboard listener: GetMessage()=%s", ret)
            if ret == -1:
                raise WinError(get_last_error())
            if ret == 0:
                keylog("GetMessage()=0, exiting loop")
                return
            r = TranslateMessage(lpmsg)
            keylog("TranslateMessage(%#x)=%s", lpmsg, r)
            r = DispatchMessageA(lpmsg)
            keylog("DispatchMessageA(%#x)=%s", lpmsg, r)
