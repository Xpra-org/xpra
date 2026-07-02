# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import byref, sizeof

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.common import INPUT, SendInput, GetAsyncKeyState, GetKeyState
from xpra.platform.win32.keyboard import VK_NAMES, NATIVE_HELD_VKS, NATIVE_TOGGLED_VKS, fake_key
from xpra.platform.win32.keyboard_config import KeyboardConfig
from xpra.server.shadow.keyboard import ShadowKeyboardManager
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("keyboard")


VK_BY_NAME: dict[str, int] = {name: vk for vk, name in VK_NAMES.items()}


class Win32ShadowKeyboardManager(ShadowKeyboardManager):
    """
    Win32 keyboard subsystem for shadow servers.
    """
    BACKEND = "win32"

    def get_keyboard_config(self, _props=None) -> KeyboardConfig:
        return KeyboardConfig()

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, kattrs: dict) -> None:
        if self.is_readonly(proto):
            return
        attrs = typedict(kattrs)
        if attrs.strget("backend") == "win32":
            vk_code = attrs.intget("vk-code", 0)
            if vk_code:
                self._native_key_event(proto, wid, keyname, pressed, attrs, vk_code)
                return
        super().do_process_keyboard_event(proto, wid, keyname, pressed, kattrs)

    def _native_key_event(self, proto, wid: int, keyname: str, pressed: bool,
                          attrs: typedict, vk_code: int) -> None:
        scancode = attrs.intget("scancode", 0)
        extended = attrs.boolget("extended", False)
        ss = self.get_server_source(proto)
        if ss is None:
            return
        self.server.set_ui_driver(ss)
        if window := self.get_subsystem("window"):
            window._focus(ss, wid, None)
        self._sync_native_modifiers(ss, attrs, vk_code)
        flags = 0
        if not pressed:
            flags |= win32con.KEYEVENTF_KEYUP
        if extended:
            flags |= win32con.KEYEVENTF_EXTENDEDKEY
        log("native_key_event: vk=%#x, scancode=%#x, extended=%s, pressed=%s, keyname=%r",
            vk_code, scancode, extended, pressed, keyname)
        inp = INPUT(type=win32con.INPUT_KEYBOARD)
        inp.ki.wVk = vk_code
        inp.ki.wScan = scancode
        inp.ki.dwFlags = flags
        inp.ki.time = 0
        inp.ki.dwExtraInfo = 0
        SendInput(1, byref(inp), sizeof(INPUT))
        if pressed:
            self.keys_pressed[vk_code] = keyname
        else:
            self.keys_pressed.pop(vk_code, None)
        ss.user_event("key-action")

    @staticmethod
    def _sync_native_modifiers(ss, attrs: typedict, ignore_vk: int) -> None:
        native_raw = attrs.dictget("native-modifiers")
        if native_raw is None:
            # Older client without native modifiers: use the existing X11 sync path
            kc = getattr(ss, "keyboard_config", None)
            if kc:
                modifiers = list(attrs.strtupleget("modifiers"))
                kc.make_keymask_match(modifiers, ignored_modifier_keycode=ignore_vk)
            return
        native = typedict(native_raw)
        wanted_held = {VK_BY_NAME[n] for n in native.strtupleget("held") if n in VK_BY_NAME}
        wanted_toggled = {VK_BY_NAME[n] for n in native.strtupleget("toggled") if n in VK_BY_NAME}
        log("sync_native_modifiers: wanted held=%s, toggled=%s, ignore_vk=%#x",
            wanted_held, wanted_toggled, ignore_vk)
        for vk in NATIVE_HELD_VKS:
            if vk == ignore_vk:
                continue
            is_held = bool(GetAsyncKeyState(vk) & 0x8000)
            want = vk in wanted_held
            if is_held != want:
                log("sync_native_modifiers: %s held %s -> %s", VK_NAMES.get(vk, vk), is_held, want)
                fake_key(vk, want)
        for vk in NATIVE_TOGGLED_VKS:
            if vk == ignore_vk:
                continue
            is_on = bool(GetKeyState(vk) & 0x0001)
            want = vk in wanted_toggled
            if is_on != want:
                log("sync_native_modifiers: %s toggle %s -> %s", VK_NAMES.get(vk, vk), is_on, want)
                fake_key(vk, True)
                fake_key(vk, False)
