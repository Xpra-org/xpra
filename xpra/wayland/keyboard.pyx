#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic
from typing import Tuple

from xpra.log import Logger

from libc.stdlib cimport free, calloc
from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint64_t, uint32_t, int32_t
from xpra.wayland.wlroots cimport (
    wlr_seat, wlr_surface, wlr_xdg_surface, wlr_keyboard, wlr_keyboard_impl, wlr_keyboard_init, wlr_keyboard_finish,
    wlr_seat_set_keyboard, wlr_seat_keyboard_notify_key, wlr_seat_keyboard_notify_modifiers,
    wlr_seat_keyboard_notify_enter, wlr_seat_keyboard_clear_focus,
    wlr_keyboard_modifiers, wlr_keyboard_set_repeat_info, wlr_keyboard_notify_modifiers,
    WL_KEYBOARD_KEY_STATE_PRESSED, WL_KEYBOARD_KEY_STATE_RELEASED,
    xkb_context, xkb_context_new, xkb_context_unref,
    xkb_keymap, xkb_keymap_unref, wlr_keyboard_set_keymap, xkb_rule_names, xkb_keymap_new_from_names,
    XKB_CONTEXT_NO_FLAGS, XKB_KEYMAP_COMPILE_NO_FLAGS,
)

log = Logger("wayland", "keyboard")

base_time = monotonic()

MOD_INDEX = {
    "shift": 0,
    "lock": 1,
    "control": 2,
    "mod1": 3,
    "mod2": 4,
    "mod3": 5,
    "mod4": 6,
    "mod5": 7,
}
LOCKED_MODIFIERS = frozenset(("lock", "mod2"))


cdef inline uint32_t get_time_msec() noexcept:
    return round((monotonic() - base_time) * 1000)


cdef inline bytes b(s: str):
    if not s:
        return b""
    return s.encode("latin1")


cdef void virtual_keyboard_led_update(wlr_keyboard *wlr_kb, uint32_t leds) noexcept:
    """Called when LED state changes (Caps Lock, Num Lock, etc.)"""
    log.info("led-update: %#x", leds)


cdef class WaylandKeyboard:
    cdef wlr_seat *seat
    cdef wlr_keyboard *keyboard
    cdef wlr_keyboard_impl keyboard_impl
    cdef object modifiers
    cdef int group

    def __init__(self, uintptr_t seat_ptr):
        self.seat = <wlr_seat*>seat_ptr
        self.modifiers = ()
        self.group = 0
        if not seat_ptr:
            raise ValueError("seat pointer is NULL")
        self.keyboard = <wlr_keyboard*> calloc(1, sizeof(wlr_keyboard))
        if not self.keyboard:
            raise MemoryError("failed to allocate keyboard")
        log("wlr_keyboard=%#x", <uintptr_t> self.keyboard)
        self.keyboard_impl.name = b"xpra-virtual-keyboard"
        self.keyboard_impl.led_update = virtual_keyboard_led_update
        wlr_keyboard_init(self.keyboard, &self.keyboard_impl, b"virtual-keyboard")
        self.set_layout()
        # set a default repeat rate:
        wlr_keyboard_set_repeat_info(self.keyboard, 25, 600)
        wlr_seat_set_keyboard(self.seat, self.keyboard)

    def __repr__(self):
        return "WaylandKeyboard(%#x)" % (<uintptr_t> self.seat)

    def cleanup(self) -> None:
        if self.keyboard:
            wlr_keyboard_finish(self.keyboard)
            free(self.keyboard)
            self.keyboard = NULL

    def set_layout(self, layout="us", model="pc105", variant="", options="") -> None:
        cdef xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS)
        if context == NULL:
            raise RuntimeError("failed to create new xkb context")
        cdef xkb_rule_names rules
        memset(&rules, 0, sizeof(xkb_rule_names))
        rules.rules = NULL
        bmodel = b(model)
        blayout = b(layout)
        rules.model = bmodel
        rules.layout = blayout
        if variant:
            bvariant = b(variant)
            rules.variant = bvariant
        if options:
            boptions = b(options)
            rules.options = boptions
        cdef xkb_keymap *keymap = xkb_keymap_new_from_names(context, &rules, XKB_KEYMAP_COMPILE_NO_FLAGS)
        if keymap == NULL:
            raise RuntimeError(f"failed to set keymap layout {layout!r}")
        wlr_keyboard_set_keymap(self.keyboard, keymap)
        xkb_keymap_unref(keymap)
        xkb_context_unref(context)

    def press_key(self, keycode: int, press: bool) -> None:
        cdef uint32_t time_msec = get_time_msec()
        cdef uint32_t state = WL_KEYBOARD_KEY_STATE_PRESSED if press else WL_KEYBOARD_KEY_STATE_RELEASED
        if self.keyboard != NULL:
            log("wlr_seat_keyboard_notify_key(%#x, %i, %i, %i)", <uintptr_t> self.seat, time_msec, keycode, state)
            wlr_seat_keyboard_notify_key(self.seat, time_msec, keycode - 8, state)


    def clear_keys_pressed(self, keycodes) -> None:
        """ this is not a real keyboard """

    def set_repeat_rate(self, delay: int, interval: int) -> None:
        cdef uint32_t irate = round(1000 / interval)
        cdef uint32_t idelay = delay
        if self.keyboard != NULL:
            wlr_keyboard_set_repeat_info(self.keyboard, irate, idelay)
            log("wlr_keyboard_set_repeat_info(%#x, %i, %i)", <uintptr_t> self.keyboard, irate, idelay)

    def get_keycodes_down(self) -> Sequence[int]:
        return ()

    def get_layout_group(self) -> int:
        return self.group

    def set_layout_group(self, group: int) -> None:
        self.update_modifiers(self.modifiers, group)

    def reapply_modifiers(self) -> None:
        self.update_modifiers(self.modifiers, self.group)

    def update_modifiers(self, modifiers=(), group: int = 0) -> None:
        cdef uint32_t depressed = 0
        cdef uint32_t locked = 0
        cdef uint32_t bit = 0
        cdef str modifier
        self.modifiers = tuple(x for x in (modifiers or ()) if x)
        self.group = group
        if self.keyboard == NULL:
            return
        for modifier in self.modifiers:
            bit = self.modifier_bit(modifier)
            if not bit:
                continue
            if modifier in LOCKED_MODIFIERS:
                locked |= bit
            else:
                depressed |= bit
        log("update_modifiers(%s, group=%i) depressed=%#x locked=%#x",
            self.modifiers, self.group, depressed, locked)
        wlr_keyboard_notify_modifiers(self.keyboard, depressed, 0, locked, group)
        wlr_seat_keyboard_notify_modifiers(self.seat, &self.keyboard.modifiers)

    cdef uint32_t modifier_bit(self, str modifier):
        cdef int index = MOD_INDEX.get(modifier, -1)
        if index < 0 or index >= 8:
            return 0
        cdef uint32_t mod_index = self.keyboard.mod_indexes[index]
        if mod_index == <uint32_t> -1:
            return 0
        return 1 << mod_index

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

        wlr_seat_keyboard_notify_enter(self.seat, surface,
                                       self.keyboard.keycodes, self.keyboard.num_keycodes, &self.keyboard.modifiers)
        log("keyboard.focus(%#x) done", xdg_surface_ptr)
