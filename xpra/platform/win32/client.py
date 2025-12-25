# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import (
    Structure, POINTER, byref, get_last_error,
    create_string_buffer, c_int, CFUNCTYPE, WinError, c_char_p,
)
from ctypes.wintypes import DWORD, WPARAM, LPARAM, MSG

from xpra.client.base import features
from xpra.client.base.stub import StubClientMixin
from xpra.exit_codes import ExitCode
from xpra.keyboard.common import KeyEvent
from xpra.platform.win32 import constants as win32con, setup_console_event_listener
from xpra.platform.win32.common import (
    GetIntSystemParametersInfo, UnhookWindowsHookEx, GetKeyboardLayoutName,
    CallNextHookEx, GetKeyState, SetWindowsHookExA, GetModuleHandleA, GetMessageA, TranslateMessage, DispatchMessageA,
)
from xpra.platform.win32.events import KNOWN_EVENTS, Win32Eventlistener, get_win32_event_listener
from xpra.platform.win32.gui import (
    WM_WTSSESSION_CHANGE, FORWARD_WINDOWS_KEY, POLL_LAYOUT, grablog, keylog, WTS_SESSION_EVENTS, WTS_SESSION_LOGOFF,
    WTS_SESSION_LOCK, WTS_SESSION_LOGON, WTS_SESSION_UNLOCK,
)
from xpra.common import noop
from xpra.util.env import envint, envbool
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "events")

GLib = gi_import("GLib")

CONSOLE_EVENT_LISTENER = envbool("XPRA_CONSOLE_EVENT_LISTENER", True)
SCREENSAVER_LISTENER_POLL_DELAY = envint("XPRA_SCREENSAVER_LISTENER_POLL_DELAY", 10)

log(f"win32 native client settings: {CONSOLE_EVENT_LISTENER=}")

ALL_KEY_EVENTS: dict[int, str] = {
    win32con.WM_KEYDOWN: "KEYDOWN",
    win32con.WM_SYSKEYDOWN: "SYSKEYDOWN",
    win32con.WM_KEYUP: "KEYUP",
    win32con.WM_SYSKEYUP: "SYSKEYUP",
}

KEY_DOWN_EVENTS = [win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN]
# UP = [win32con.WM_KEYUP, win32con.WM_SYSKEYUP]

CONSOLE_INFO_EVENTS = [
    win32con.CTRL_C_EVENT,
    win32con.CTRL_LOGOFF_EVENT,
    win32con.CTRL_BREAK_EVENT,
    win32con.CTRL_SHUTDOWN_EVENT,
    win32con.CTRL_CLOSE_EVENT,
]


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
    log(f"layout-name={name_buf.value!r}")
    try:
        # win32 API returns a hex string
        return int(name_buf.value, 16)
    except ValueError:
        log.warn("Warning: failed to parse keyboard layout code '%s'", name_buf.value)
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
    # keylog.info("keyboard helper=%s, modifier keycodes=%s", kh, modifier_keycodes)
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


class PlatformClient(StubClientMixin):
    def __init__(self):
        self._kh_warning = False
        self._console_handler_added = False
        self._screensaver_state = False
        self._screensaver_timer = 0
        self._keyboard_poll_exit = False
        self._keyboard_hook_id = 0
        self._keyboard_poll_timer: int = 0
        self._keyboard_id: int = 0
        self._eventlistener: Win32Eventlistener | None = None

    def run(self):
        if SCREENSAVER_LISTENER_POLL_DELAY > 0:
            self._screensaver_timer = GLib.timeout_add(SCREENSAVER_LISTENER_POLL_DELAY * 1000, self.poll_screensaver)
        if CONSOLE_EVENT_LISTENER:
            self._console_handler_added = setup_console_event_listener(self.handle_console_event, True)
        self.init_event_listener()
        self._keyboard_id: int = get_keyboard_layout_id()
        if FORWARD_WINDOWS_KEY and features.keyboard and features.window:
            from xpra.util.thread import start_thread
            start_thread(self.run_keyboard_listener, "keyboard-listener", daemon=True)

    def init_event_listener(self) -> None:
        try:
            el = get_win32_event_listener(True)
            self._eventlistener = el
            if el:
                el.add_event_callback(win32con.WM_ACTIVATEAPP, self.activateapp)
                el.add_event_callback(win32con.WM_MOVE, self.wm_move)
                el.add_event_callback(WM_WTSSESSION_CHANGE, self.session_change_event)
                el.add_event_callback(win32con.WM_INPUTLANGCHANGE, self.inputlangchange)
                el.add_event_callback(win32con.WM_WININICHANGE, self.inichange)
                el.add_event_callback(win32con.WM_ENDSESSION, self.end_session)
        except Exception as e:
            log.error("Error: cannot register focus and session callbacks:")
            log.estr(e)

    def cleanup(self) -> None:
        log("PlatformClient.cleanup()")
        self._keyboard_poll_exit = True
        cha = self._console_handler_added
        if cha:
            self._console_handler_added = False
            # removing can cause crashes!?
            # setup_console_event_listener(self.handle_console_event, False)
        el = self._eventlistener
        if el:
            self._eventlistener = None
            el.cleanup()
        khid = self._keyboard_hook_id
        if khid:
            self._keyboard_hook_id = 0
            UnhookWindowsHookEx(khid)
        kpt = self._keyboard_poll_timer
        if kpt:
            self._keyboard_poll_timer = 0
            GLib.source_remove(kpt)
        sst = self._screensaver_timer
        if sst:
            self._screensaver_timer = 0
            GLib.source_remove(sst)
        log("PlatformClient.cleanup() ended")

    def poll_screensaver(self) -> bool:
        v = bool(GetIntSystemParametersInfo(win32con.SPI_GETSCREENSAVERRUNNING))
        log("SPI_GETSCREENSAVERRUNNING=%s", v)
        if self._screensaver_state != v:
            self._screensaver_state = v
            if v:
                self.suspend()
            else:
                self.resume()
        return True

    def poll_layout(self) -> None:
        self._keyboard_poll_timer = 0
        klid = get_keyboard_layout_id()
        if klid and klid != self._keyboard_id:
            self._keyboard_id = klid
            self.window_keyboard_layout_changed()

    def run_keyboard_listener(self) -> None:

        def low_level_keyboard_handler(ncode: int, wparam: int, lparam: int):
            log("WH_KEYBOARD_LL: %s", (ncode, wparam, lparam))
            kh = getattr(self, "keyboard_helper", None)
            locked = getattr(kh, "locked", False)
            if POLL_LAYOUT and self._keyboard_poll_timer == 0 and not locked:
                self._keyboard_poll_timer = GLib.timeout_add(POLL_LAYOUT, self.poll_layout)
            # docs say we should not process events with ncode < 0:
            if ncode >= 0 and kh and kh.keyboard and lparam:
                try:
                    scan_code = lparam.contents.scan_code
                    vk_code = lparam.contents.vk_code
                    focused = getattr(self, "_focused", False)
                    # the keys we want intercept before the OS:
                    trap = vk_code in (win32con.VK_LWIN, win32con.VK_RWIN, win32con.VK_TAB)
                    key_event_type = ALL_KEY_EVENTS.get(wparam)
                    if self.keyboard_grabbed and focused and trap and key_event_type:
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
        _keyboard_hook_id = SetWindowsHookExA(win32con.WH_KEYBOARD_LL, pointer, GetModuleHandleA(None), 0)
        # Register to remove the hook when the interpreter exits:
        keylog("run_keyboard_listener() hook_id=%#x", _keyboard_hook_id)
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

    def wm_move(self, wparam: int, lparam: int) -> None:
        log("WM_MOVE: %s/%s", wparam, lparam)
        # this is not really a screen size change event,
        # but we do want to process it as such (see window reinit code)
        self.screen_size_changed()

    def end_session(self, wparam: int, lparam: int) -> None:
        log(f"WM_ENDSESSION({wparam}, {lparam})")
        ENDSESSION_CLOSEAPP = 0x1
        ENDSESSION_CRITICAL = 0x40000000
        ENDSESSION_LOGOFF = 0x80000000
        if (wparam & ENDSESSION_CLOSEAPP) and wparam:
            reason = "restart manager request"
        elif wparam & ENDSESSION_CRITICAL:
            reason = "application forced to shutdown"
        elif wparam & ENDSESSION_LOGOFF:
            reason = "logoff"
        else:
            return
        handler = getattr(self, "disconnect_and_quit", noop)
        handler(ExitCode.OK, reason)

    def session_change_event(self, event: int, session: int) -> None:
        event_name = WTS_SESSION_EVENTS.get(event) or str(event)
        log("WM_WTSSESSION_CHANGE: %s on session %#x", event_name, session)
        handler = noop
        if event in (WTS_SESSION_LOGOFF, WTS_SESSION_LOCK):
            handler = getattr(self, "freeze", noop)
            log(f"will freeze all the windows: {handler=!r}")
        elif event in (WTS_SESSION_LOGON, WTS_SESSION_UNLOCK):
            handler = getattr(self, "unfreeze", noop)
            log(f"will unfreeze all the windows: {handler=!r}")
        if handler != noop:
            # don't freeze or unfreeze directly from here,
            # as the system may not be fully usable yet (see #997)
            GLib.idle_add(handler)

    def inputlangchange(self, wparam: int, lparam: int) -> None:
        keylog("WM_INPUTLANGCHANGE: %i, %i", wparam, lparam)
        self.poll_layout()

    def inichange(self, wparam: int, lparam: int) -> None:
        if lparam:
            log("WM_WININICHANGE: %#x=%s", lparam, c_char_p(lparam).value)
        else:
            log("WM_WININICHANGE: %i, %i", wparam, lparam)

    def activateapp(self, wparam: int, lparam: int) -> None:
        log("WM_ACTIVATEAPP: %s/%s", wparam, lparam)
        if not features.window:
            return
        if wparam == 0:
            # our app has lost focus
            self.update_focus(0, False)
        # workaround for windows losing their style:
        for window in self._id_to_window.values():
            fixup_window_style = getattr(window, "fixup_window_style", None)
            if fixup_window_style:
                fixup_window_style()

    def handle_console_event(self, event: int) -> int:
        event_name = KNOWN_EVENTS.get(event, event)
        log("handle_console_event(%s) event_name=%s", event, event_name)
        if event in CONSOLE_INFO_EVENTS:
            log.info("received console event %s", str(event_name).replace("_EVENT", ""))
        else:
            log.warn("unknown console event: %s", event_name)
        handler = getattr(self, "signal_disconnect_and_quit", noop)
        if event == win32con.CTRL_C_EVENT:
            log("calling=%s", handler)
            handler(0, "CTRL_C")
            return 1
        if event == win32con.CTRL_CLOSE_EVENT:
            handler(0, "CTRL_CLOSE")
            return 1
        return 0
