# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

# GTK-on-win32 glue: code that reaches into GDK-Win32 internals (via
# `libgdk-3-0.dll`) or hooks GTK window objects. This lives apart from
# `xpra.platform.win32.gui` (which is toolkit-agnostic) so that importing
# `gui.py` - as the native win32 client backend does - stays GDK-free.

import types
from ctypes import CDLL, pythonapi, py_object
from ctypes.util import find_library
from ctypes.wintypes import HWND, HGDIOBJ

from xpra.platform.win32 import constants as win32con
from xpra.platform.win32.window_hooks import Win32Hooks
from xpra.log import Logger

log = Logger("win32")
keylog = Logger("win32", "keyboard")
pointerlog = Logger("win32", "pointer")

PyCapsule_GetPointer = pythonapi.PyCapsule_GetPointer
PyCapsule_GetPointer.restype = HGDIOBJ
PyCapsule_GetPointer.argtypes = [py_object]
log("PyCapsule_GetPointer=%s", PyCapsule_GetPointer)

GDK_DLL_NAME = "libgdk-3-0.dll"
gdk_dll = find_library(GDK_DLL_NAME)
if not gdk_dll:
    raise ImportError(f"ctypes cannot find {GDK_DLL_NAME!r}")
gdkdll = CDLL(gdk_dll)
gdk_win32_window_get_handle = gdkdll.gdk_win32_window_get_handle
gdk_win32_window_get_handle.argtypes = [HGDIOBJ]
gdk_win32_window_get_handle.restype = HWND
log("gdkdll=%s", gdkdll)


def get_window_handle(window) -> int:
    """ returns the win32 hwnd from a gtk.Window or gdk.Window """
    gdk_window = window
    try:
        gdk_window = window.get_window()
    except Exception:
        pass
    if not gdk_window:
        return 0
    gpointer = PyCapsule_GetPointer(gdk_window.__gpointer__, None)
    hwnd = gdk_win32_window_get_handle(gpointer)
    # log("get_window_handle(%s) gpointer=%#x, hwnd=%#x", gpointer, hwnd)
    return hwnd


def win32_propsys_set_group_leader(self, leader):
    """ implements set group leader using propsys """
    # `self` and `leader` are raw GDK windows here (this is bound as
    # `gdk_window.set_group`), so we need the GTK -> HWND helper:
    from xpra.platform.win32.gui import set_window_group
    hwnd = get_window_handle(self)
    if not hwnd:
        return
    try:
        log("win32_propsys_set_group_leader(%s)", leader)
        lhandle = get_window_handle(leader)
        assert lhandle
    except Exception:
        log("win32_propsys_set_group_leader(%s)", leader, exc_info=True)
        log.warn("Warning: no window handle for %s", leader)
        log.warn(" cannot set window grouping attribute")
        return
    if not lhandle:
        return
    try:
        log("win32 hooks: get_window_handle(%s)=%#x, set_group(%#x)", self, hwnd, lhandle)
        set_window_group(hwnd, lhandle)
    except Exception as e:
        log("set_window_group error", exc_info=True)
        log.error("Error: failed to set group leader")
        log.estr(e)


def add_window_hooks(window) -> None:
    # the win32 primitives + toggle flags + smaller helpers live in `gui.py`;
    # only this GTK-coupled orchestration (which hooks GTK window methods and
    # the GDK window object) belongs here:
    from xpra.platform.win32.gui import (
        no_set_group,
        fixup_window_style, set_decorated, window_state_updated,
        apply_geometry_hints, apply_maxsize_hints,
        pointer_grab, pointer_ungrab, _apply_title_bar_theme, set_window_group,
        WINDOW_HOOKS, GROUP_LEADER, UNDECORATED_STYLE, MAX_SIZE_HINT,
        CLIP_CURSOR, LANGCHANGE, WHEEL, WHEEL_DELTA,
    )
    log("add_window_hooks(%s) WINDOW_HOOKS=%s, GROUP_LEADER=%s, UNDECORATED_STYLE=%s",
        window, WINDOW_HOOKS, GROUP_LEADER, UNDECORATED_STYLE)
    log(" MAX_SIZE_HINT=%s, MAX_SIZE_HINT=%s", MAX_SIZE_HINT, MAX_SIZE_HINT)
    if not WINDOW_HOOKS:
        # allows us to disable the win32 hooks for testing
        return
    try:
        gdk_window = window.get_window()
    except Exception:
        gdk_window = None
    if not gdk_window:
        # can't get a handle from a None value...
        return
    # at least provide a dummy method:
    gdk_window.set_group = no_set_group
    handle = window.get_window_handle()
    if not handle:
        log.warn("Warning: cannot add window hooks without a window handle!")
        return
    log("add_window_hooks(%s) gdk window=%s, hwnd=%#x", window, gdk_window, handle)

    try:
        _apply_title_bar_theme(handle)
    except Exception:
        log("_apply_title_bar_theme(%#x)", handle, exc_info=True)

    if GROUP_LEADER:
        # MSWindows 7 onwards can use AppUserModel to emulate the group leader stuff:
        log("win32 hooks: set_window_group=%s", set_window_group)
        gdk_window.set_group = types.MethodType(win32_propsys_set_group_leader, gdk_window)
        log("hooked group leader override using %s", set_window_group)

    if UNDECORATED_STYLE:
        # OR windows never have any decorations or taskbar menu
        if not window._override_redirect:
            # the method to call to fix things up:
            window.fixup_window_style = types.MethodType(fixup_window_style, window)
            # override `set_decorated` so we can preserve the taskbar menu for undecorated windows
            window.__set_decorated = window.set_decorated
            window.set_decorated = types.MethodType(set_decorated, window)
            # override `after_window_state_updated` so we can re-add the missing style options
            # (somehow doing it from on_realize which calls add_window_hooks is not enough)
            window.connect("state-updated", window_state_updated)
            # call it at least once:
            window.fixup_window_style()

    if CLIP_CURSOR:
        window.pointer_grab = types.MethodType(pointer_grab, window)
        window.pointer_ungrab = types.MethodType(pointer_ungrab, window)

    if MAX_SIZE_HINT or LANGCHANGE or WHEEL:
        # glue code for gtk to win32 APIs:
        # add event hook class:
        win32hooks = Win32Hooks(handle)
        log("add_window_hooks(%s) added hooks for hwnd %#x: %s", window, handle, win32hooks)
        window.win32hooks = win32hooks
        win32hooks.setup()

        if MAX_SIZE_HINT:
            # save original geometry function:
            window.__apply_geometry_hints = window.apply_geometry_hints
            window.apply_geometry_hints = types.MethodType(apply_geometry_hints, window)
            # apply current max-size from hints, if any:
            if window.geometry_hints:
                apply_maxsize_hints(window, window.geometry_hints)

        if LANGCHANGE:
            def inputlangchange(_hwnd: int, _event: int, wParam: int, lParam: int) -> int:
                keylog("WM_INPUTLANGCHANGE: character set: %i, input locale identifier: %i", wParam, lParam)
                window.keyboard_layout_changed("WM_INPUTLANGCHANGE", wParam, lParam)
                return 0

            win32hooks.add_window_event_handler(win32con.WM_INPUTLANGCHANGE, inputlangchange)

        if WHEEL:
            VERTICAL = "vertical"
            HORIZONTAL = "horizontal"

            def handle_wheel(orientation: str, wParam: int, lParam: int):
                distance = wParam >> 16
                if distance > 2 ** 15:
                    # ie: 0xFF88 -> 0x78 (120)
                    distance = distance - 2 ** 16
                keys = wParam & 0xFFFF
                y = lParam >> 16
                x = lParam & 0xFFFF
                units = distance / WHEEL_DELTA
                client = getattr(window, "_client")
                wid = getattr(window, "_id", 0)
                pointerlog(
                    "win32 mousewheel: orientation=%s, distance=%i, wheel-delta=%s, units=%.3f, new value=%.1f, keys=%#x, x=%i, y=%i, client=%s, wid=%#x",
                    orientation, distance, WHEEL_DELTA, units, distance, keys, x, y, client, wid)
                if client and wid > 0:
                    if orientation == VERTICAL:
                        deltax = 0
                        deltay = units
                    else:
                        deltax = units
                        deltay = 0
                    pointer = window.get_mouse_position()
                    device_id = -1
                    if wp := client.get_subsystem("window"):
                        wp.wheel_event(device_id, wid, deltax, deltay, pointer)

            def mousewheel(_hwnd: int, _event: int, wParam: int, lParam: int) -> int:
                handle_wheel(VERTICAL, wParam, lParam)
                return 0

            def mousehwheel(_hwnd: int, _event: int, wParam: int, lParam: int) -> int:
                handle_wheel(HORIZONTAL, wParam, lParam)
                return 0

            win32hooks.add_window_event_handler(win32con.WM_MOUSEWHEEL, mousewheel)
            win32hooks.add_window_event_handler(win32con.WM_MOUSEHWHEEL, mousehwheel)
