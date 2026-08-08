# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import win32con
from ctypes import byref, WINFUNCTYPE, c_size_t
from ctypes.wintypes import MSG, HWND, UINT, DWORD

from xpra.platform.win32.common import PeekMessageW, TranslateMessage, DispatchMessageW, SetTimer, KillTimer
from xpra.os_util import gi_import
from xpra.log import Logger

log = Logger("win32")

GLib = gi_import("GLib")

# the single Windows message source, set by `inject_windows_message_source`;
# the modal-loop pump needs to reach it to make it inert (see `start_modal_message_pump`):
_win_message_source = None


class WindowsMessageSource(GLib.Source):
    """Custom GLib source that processes Windows messages"""

    def __init__(self):
        super().__init__()
        self.msg = MSG()
        self.main_loop = None
        # while a native modal loop is running (window drag / resize), the win32
        # message queue is pumped by `DefWindowProc` itself; this source must stay
        # inert so it does not steal (via `PM_REMOVE`) the input messages that the
        # modal loop relies on - see `iterate_main_context`:
        self.modal = False
        # Set high priority so Windows messages are processed promptly
        self.set_priority(GLib.PRIORITY_HIGH)

    def prepare(self):
        # log("prepare()")
        """Check if messages are available without blocking"""
        # Return (ready, timeout)
        # timeout=-1 means wait indefinitely, 0 means don't wait
        if self.modal:
            return False, 10
        has_message = PeekMessageW(
            byref(self.msg),
            None,  # All windows
            0, 0,  # All messages
            win32con.PM_NOREMOVE  # Don't remove from queue
        )
        # If messages available, dispatch immediately (timeout=0)
        # If no messages, check again in 10ms (timeout=10)
        timeout = 0 if has_message else 10
        return has_message != 0, timeout

    def check(self):
        """Check if source is ready to dispatch"""
        if self.modal:
            return False
        has_message = PeekMessageW(
            byref(self.msg),
            None,
            0, 0,
            win32con.PM_NOREMOVE
        )
        # log("check() PeekMessage(..)=%s", has_message != 0)
        return has_message != 0

    # noinspection PyUnusedLocal
    def dispatch(self, callback, user_data):
        """
        Process a LIMITED number of Windows messages per call
        This allows GLib main loop to run and Windows to do background work

        ``callback`` and ``user_data`` are part of GLib's ``GSource.dispatch``
        signature for custom sources.
        """
        max_messages = 5
        processed = 0
        pmsg = byref(self.msg)
        while processed < max_messages and PeekMessageW(pmsg, None, 0, 0, win32con.PM_REMOVE):
            msgid = self.msg.message
            # log("dispatch message=%s", WM_MESSAGES.get(msgid, msgid))
            if msgid == win32con.WM_QUIT:
                # Quit the GLib main loop when Windows sends WM_QUIT
                if self.main_loop:
                    self.main_loop.quit()
                return False

            TranslateMessage(pmsg)
            DispatchMessageW(pmsg)
            processed += 1

        # Continue running this source
        return True


def process_windows_messages():
    """Process Windows messages - called by GLib timer"""
    msg = MSG()
    processed = 0
    max_per_call = 5

    while processed < max_per_call and PeekMessageW(byref(msg), None, 0, 0, win32con.PM_REMOVE):
        msgid = msg.message
        # log("Timer dispatch: %s", WM_MESSAGES.get(msgid, msgid))
        if msgid == win32con.WM_QUIT:
            return False  # Stop timer

        TranslateMessage(byref(msg))
        DispatchMessageW(byref(msg))
        processed += 1

    return True  # Continue timer


# Native modal loops (window drag / resize, menu tracking) run their own
# `GetMessage`/`DispatchMessage` loop inside `DefWindowProc` / `TrackPopupMenu`
# and never return to GLib, which would starve every GLib idle/timeout callback
# (screen updates, the UI watcher ping, ...) for the duration of the interaction.
#
# We install a win32 timer with a `TIMERPROC` callback: `WM_TIMER` messages are
# delivered *inside* the modal loop, and because we pass a callback, the modal
# loop's `DispatchMessage` invokes it directly (no window procedure involved), so
# the very same mechanism works for any HWND without hooking its WndProc.
MODAL_PUMP_TIMER_ID = 0xE17A  # arbitrary, unlikely to clash with app timers
MODAL_PUMP_INTERVAL_MS = 10  # ~100Hz, matches the normal message-source polling

# void CALLBACK TimerProc(HWND, UINT uMsg, UINT_PTR idEvent, DWORD dwTime)
TIMERPROC = WINFUNCTYPE(None, HWND, UINT, c_size_t, DWORD)

# number of nested modal loops currently pumping (menus can nest, e.g. a submenu):
_modal_depth = 0

# `Gdk` attaches its own event source to the default main context, and it drains
# the win32 message queue exactly like `WindowsMessageSource` does
# (`PeekMessageW(NULL, PM_REMOVE)` + `DispatchMessageW`).
# That is harmless in normal operation - either pump delivers each message to the
# window procedure that owns it - but it is fatal inside a native modal loop:
# the loop needs to see `WM_MOUSEMOVE` / `WM_LBUTTONUP` itself, and a stolen
# button-up means the drag never ends.
# `WindowsMessageSource` has the `modal` flag for this; `Gdk`'s source does not,
# so `iterate_main_context` demotes it below `MODAL_PRIORITY_CUTOFF` and skips it.
# Left as `None` unless Gtk was actually loaded (see `xpra.client.win32.gtk`),
# in which case `iterate_main_context` behaves exactly as it always has:
_gdk_source = None
MODAL_PRIORITY_CUTOFF = GLib.PRIORITY_LOW


def set_gdk_event_source(source) -> None:
    global _gdk_source
    log("set_gdk_event_source(%s)", source)
    _gdk_source = source


def _on_pump_timer(_hwnd, _msg, _timer_id, _dwtime) -> None:
    iterate_main_context()


# keep a single reference to the ctypes callback alive for the process lifetime
# (if it were garbage-collected while a timer is armed, the callback would crash):
_timer_proc_ref = TIMERPROC(_on_pump_timer)


def start_modal_message_pump(hwnd: int) -> None:
    """Called when `hwnd` is about to enter a native modal move/resize/menu loop."""
    global _modal_depth
    _modal_depth += 1
    if _win_message_source is not None:
        # stop our GLib source from stealing (via `PM_REMOVE`) the input messages
        # the modal loop relies on - `iterate_main_context` will run the rest:
        _win_message_source.modal = True
    SetTimer(hwnd, MODAL_PUMP_TIMER_ID, MODAL_PUMP_INTERVAL_MS, _timer_proc_ref)
    log("start_modal_message_pump(%#x) depth=%i", hwnd, _modal_depth)


def stop_modal_message_pump(hwnd: int) -> None:
    """Called when `hwnd` leaves a native modal move/resize/menu loop."""
    global _modal_depth
    KillTimer(hwnd, MODAL_PUMP_TIMER_ID)
    _modal_depth = max(0, _modal_depth - 1)
    if _modal_depth == 0 and _win_message_source is not None:
        _win_message_source.modal = False
    log("stop_modal_message_pump(%#x) depth=%i", hwnd, _modal_depth)


def iterate_main_context(max_iterations: int = 32) -> None:
    """
    Flush pending GLib work without blocking.

    Driven from the modal-loop timer callback: the `WindowsMessageSource` is
    inert (`modal=True`) so this only dispatches idle/timeout sources - the modal
    loop keeps ownership of the win32 message queue.
    """
    context = GLib.MainContext.default()
    if _gdk_source is None:
        n = 0
        while n < max_iterations and context.pending():
            context.iteration(False)
            n += 1
        return
    # Gtk is loaded: `context.iteration()` would dispatch `Gdk`'s event source,
    # which would steal the messages the modal loop needs, so demote it and
    # dispatch by hand, stopping short of its priority:
    _gdk_source.set_priority(MODAL_PRIORITY_CUTOFF)
    try:
        n = 0
        while n < max_iterations:
            ready, priority = context.prepare()
            if not ready or priority >= MODAL_PRIORITY_CUTOFF:
                break
            context.query(priority)
            if not context.check(priority, []):
                break
            context.dispatch()
            n += 1
    finally:
        _gdk_source.set_priority(GLib.PRIORITY_DEFAULT)


def inject_windows_message_source(main_loop) -> int:
    global _win_message_source
    context = main_loop.get_context()
    win_source = WindowsMessageSource()
    win_source.main_loop = main_loop  # Store reference for WM_QUIT handling
    main_loop._win_message_source = win_source  # Store reference ot prevent garbage collection
    _win_message_source = win_source

    return win_source.attach(context)
