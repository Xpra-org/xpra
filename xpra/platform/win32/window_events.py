# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from ctypes import c_char_p

from xpra.platform.win32 import constants as win32con, setup_console_event_listener
from xpra.platform.win32.events import KNOWN_EVENTS, Win32Eventlistener, get_win32_event_listener
from xpra.platform.win32.gui import (
    WM_WTSSESSION_CHANGE, WTS_SESSION_EVENTS, WTS_SESSION_LOGOFF,
    WTS_SESSION_LOCK, WTS_SESSION_LOGON, WTS_SESSION_UNLOCK,
)
from xpra.exit_codes import ExitCode
from xpra.util.env import envbool
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32", "events")
GLib = gi_import("GLib")

CONSOLE_EVENT_LISTENER = envbool("XPRA_CONSOLE_EVENT_LISTENER", True)

CONSOLE_INFO_EVENTS = [
    win32con.CTRL_C_EVENT,
    win32con.CTRL_LOGOFF_EVENT,
    win32con.CTRL_BREAK_EVENT,
    win32con.CTRL_SHUTDOWN_EVENT,
    win32con.CTRL_CLOSE_EVENT,
]


class Win32ClientEventsWatcher:
    """
    Window-manager/session focus and lifecycle events (WM_ACTIVATEAPP, WM_MOVE,
    WM_WTSSESSION_CHANGE, WM_INPUTLANGCHANGE, WM_WININICHANGE, WM_ENDSESSION,
    console control events), feeding the `window` and `keyboard` subsystems and
    client-level lifecycle.
    """

    def __init__(self, window_client):
        self.window = window_client
        self._eventlistener: Win32Eventlistener | None = None
        self._console_handler_added = False

    def setup(self) -> None:
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
        if CONSOLE_EVENT_LISTENER:
            self._console_handler_added = setup_console_event_listener(self.handle_console_event, True)

    def cleanup(self) -> None:
        if self._console_handler_added:
            self._console_handler_added = False
            # removing can cause crashes!?
            # setup_console_event_listener(self.handle_console_event, False)
        if el := self._eventlistener:
            self._eventlistener = None
            el.cleanup()

    def wm_move(self, wparam: int, lparam: int) -> None:
        log("WM_MOVE: %s/%s", wparam, lparam)
        # this is not really a screen size change event,
        # but we do want to process it as such (see window reinit code)
        display = self.window.get_subsystem("display")
        if display:
            display.screen_size_changed()

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
        self.window.client.disconnect_and_quit(ExitCode.OK, reason)

    def session_change_event(self, event: int, session: int) -> None:
        event_name = WTS_SESSION_EVENTS.get(event) or str(event)
        log("WM_WTSSESSION_CHANGE: %s on session %#x", event_name, session)
        handler = None
        if event in (WTS_SESSION_LOGOFF, WTS_SESSION_LOCK):
            handler = self.window.freeze
            log(f"will freeze all the windows: {handler=!r}")
        elif event in (WTS_SESSION_LOGON, WTS_SESSION_UNLOCK):
            handler = self.window.unfreeze
            log(f"will unfreeze all the windows: {handler=!r}")
        if handler:
            # don't freeze or unfreeze directly from here,
            # as the system may not be fully usable yet (see #997)
            GLib.idle_add(handler)

    def inputlangchange(self, wparam: int, lparam: int) -> None:
        log("WM_INPUTLANGCHANGE: %i, %i", wparam, lparam)
        keyboard = self.window.get_subsystem("keyboard")
        hook = getattr(keyboard, "_win32_keyboard_hook", None) if keyboard else None
        if hook:
            hook.poll_layout()

    def inichange(self, wparam: int, lparam: int) -> None:
        if lparam:
            log("WM_WININICHANGE: %#x=%s", lparam, c_char_p(lparam).value)
        else:
            log("WM_WININICHANGE: %i, %i", wparam, lparam)

    def activateapp(self, wparam: int, lparam: int) -> None:
        log("WM_ACTIVATEAPP: %s/%s", wparam, lparam)
        if wparam == 0:
            # our app has lost focus
            self.window.update_focus(0, False)
        # workaround for windows losing their style:
        for window in self.window.get_windows():
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
        client = self.window.client
        if event == win32con.CTRL_C_EVENT:
            client.signal_disconnect_and_quit(0, "CTRL_C")
            return 1
        if event == win32con.CTRL_CLOSE_EVENT:
            client.signal_disconnect_and_quit(0, "CTRL_CLOSE")
            return 1
        return 0
