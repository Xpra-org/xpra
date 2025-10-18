#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Tuple

from xpra.log import Logger

from libc.stdint cimport uintptr_t, uint64_t, uint32_t, int32_t
from xpra.wayland.wlroots cimport (
    wlr_seat, wlr_surface, wlr_xdg_surface,
    wlr_seat_keyboard_notify_key, wlr_seat_keyboard_notify_modifiers, wlr_keyboard_modifiers,
    wlr_seat_keyboard_notify_enter, wlr_seat_keyboard_clear_focus,
    WL_KEYBOARD_KEY_STATE_PRESSED, WL_KEYBOARD_KEY_STATE_RELEASED,
)

log = Logger("wayland", "keyboard")

base_time = monotonic()


cdef uint32_t get_time_msec():
    return round((monotonic() - base_time) * 1000)


cdef class WaylandKeyboard:
    cdef wlr_seat *seat

    def __init__(self, uintptr_t seat_ptr):
        self.seat = <wlr_seat*>seat_ptr

    def press_key(self, keycode: int, press: bool) -> None:
        log("press_key%s", (keycode, press))
        cdef uint32_t time_msec = get_time_msec()
        cdef uint32_t state = WL_KEYBOARD_KEY_STATE_PRESSED if press else WL_KEYBOARD_KEY_STATE_RELEASED
        wlr_seat_keyboard_notify_key(self.seat, time_msec, keycode, state)

    def clear_keys_pressed(self, keycodes) -> None:
        """ this is not a real keyboard """

    def set_repeat_rate(self, delay: int, interval: int) -> None:
        """ this is not a real keyboard """

    def get_keycodes_down(self) -> Sequence[int]:
        return ()

    def get_layout_group(self) -> int:
        return 0

    def _update_modifiers(self, uint32_t depressed=0, uint32_t latched=0,
                         uint32_t locked=0, uint32_t group=0):
        """
            depressed: Currently pressed modifiers
            latched: Latched modifiers
            locked: Locked modifiers (Caps Lock, etc.)
            group: Keyboard layout group
        """
        cdef wlr_keyboard_modifiers mods
        mods.depressed = depressed
        mods.latched = latched
        mods.locked = locked
        mods.group = group
        wlr_seat_keyboard_notify_modifiers(self.seat, &mods)

    def focus(self, uintptr_t xdg_surface_ptr) -> None:
        if not xdg_surface_ptr:
            wlr_seat_keyboard_clear_focus(self.seat)
            log("focus(%#x) cleared focus", xdg_surface_ptr)
            return
        cdef wlr_xdg_surface *xdg_surface = <wlr_xdg_surface*> xdg_surface_ptr
        cdef wlr_surface *surface = xdg_surface.surface
        if not surface:
            log("surface is NULL, cleared focus")
            return
        cdef uint32_t keycodes[1]
        keycodes[0] = 0
        cdef wlr_keyboard_modifiers mods
        mods.depressed = 0
        mods.latched = 0
        mods.locked = 0
        mods.group = 0
        wlr_seat_keyboard_notify_enter(self.seat, surface, <uint32_t*> &keycodes, 0, &mods)
        log.warn("keyboard.focus(%#x) done", xdg_surface_ptr)
