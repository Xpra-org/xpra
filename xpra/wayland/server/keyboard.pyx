#!/usr/bin/env python3
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from time import monotonic

from xpra.log import Logger

from libc.stdlib cimport free, calloc
from libc.string cimport memset
from libc.stdint cimport uintptr_t, uint32_t
from xpra.wayland.server.wlroots cimport (
    wlr_seat, wlr_surface, wlr_xdg_surface, wlr_keyboard, wlr_keyboard_impl, wlr_keyboard_init, wlr_keyboard_finish,
    wlr_seat_set_keyboard, wlr_seat_keyboard_notify_key, wlr_seat_keyboard_notify_modifiers,
    wlr_seat_keyboard_notify_enter, wlr_seat_keyboard_clear_focus,
    wlr_keyboard_set_repeat_info, wlr_keyboard_notify_modifiers,
    WL_KEYBOARD_KEY_STATE_PRESSED, WL_KEYBOARD_KEY_STATE_RELEASED,
    xkb_context, xkb_context_new, xkb_context_unref,
    xkb_keymap, xkb_keymap_unref, wlr_keyboard_set_keymap, xkb_rule_names, xkb_keymap_new_from_names,
    XKB_CONTEXT_NO_FLAGS, XKB_KEYMAP_COMPILE_NO_FLAGS, XKB_KEYSYM_NO_FLAGS,
    xkb_keycode_t, xkb_keysym_t, xkb_layout_index_t, xkb_level_index_t,
    xkb_keymap_min_keycode, xkb_keymap_max_keycode,
    xkb_keymap_num_layouts, xkb_keymap_num_layouts_for_key, xkb_keymap_num_levels_for_key,
    xkb_keymap_key_get_syms_by_level, xkb_keysym_from_name,
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
    cdef dict keysym_to_keycode

    def __init__(self, uintptr_t seat_ptr):
        self.seat = <wlr_seat*>seat_ptr
        self.modifiers = ()
        self.group = 0
        self.keysym_to_keycode = {}
        if not seat_ptr:
            raise ValueError("seat pointer is NULL")
        self.keyboard = <wlr_keyboard*> calloc(1, sizeof(wlr_keyboard))
        if not self.keyboard:
            raise MemoryError("failed to allocate keyboard")
        log("wlr_keyboard=%#x", <uintptr_t> self.keyboard)
        self.keyboard_impl.name = b"xpra-virtual-keyboard"
        self.keyboard_impl.led_update = virtual_keyboard_led_update
        wlr_keyboard_init(self.keyboard, &self.keyboard_impl, b"virtual-keyboard")
        if not self.set_layout():
            raise RuntimeError("failed to compile the default keymap")
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

    def set_layout(self, layout="us", model="pc105", variant="", options="") -> bool:
        """
            Compile the layout and install it on the virtual keyboard.
            The layout attributes come from the client, so a layout we cannot compile
            is not a fatal error: we keep the keymap that is already installed.
        """
        if self.keyboard == NULL:
            # `cleanup` can have run before a packet gets here
            return False
        cdef xkb_context *context = xkb_context_new(XKB_CONTEXT_NO_FLAGS)
        if context == NULL:
            log.error("Error: failed to create a new xkb context")
            return False
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
            xkb_context_unref(context)
            log.warn("Warning: failed to compile the keymap for layout %r", layout)
            log.warn(" model=%r, variant=%r, options=%r", model, variant, options)
            return False
        wlr_keyboard_set_keymap(self.keyboard, keymap)
        self._build_keysym_map(keymap)
        xkb_keymap_unref(keymap)
        xkb_context_unref(context)
        log("set_layout(%r, %r, %r, %r) keymap installed", layout, model, variant, options)
        return True

    cdef void _build_keysym_map(self, xkb_keymap *keymap) noexcept:
        """
            Map each keysym to the (keycode, layout group) which produces it.
            The keymap can hold up to 4 layout groups - one per client layout,
            see `WaylandKeyboardManager.get_layout_groups` - so the group has to be
            part of the answer: it tells the caller which group to switch to
            before pressing the key.
        """
        cdef xkb_keycode_t min_kc = xkb_keymap_min_keycode(keymap)
        cdef xkb_keycode_t max_kc = xkb_keymap_max_keycode(keymap)
        cdef xkb_keycode_t kc
        cdef xkb_layout_index_t layout, n_layouts
        cdef xkb_level_index_t level, n_levels
        cdef const xkb_keysym_t *syms
        cdef int n_syms, i
        cdef unsigned int sym
        cdef dict mapping = {}
        for kc in range(min_kc, max_kc + 1):
            n_layouts = xkb_keymap_num_layouts_for_key(keymap, kc)
            for layout in range(n_layouts):
                n_levels = xkb_keymap_num_levels_for_key(keymap, kc, layout)
                for level in range(n_levels):
                    n_syms = xkb_keymap_key_get_syms_by_level(keymap, kc, layout, level, &syms)
                    for i in range(n_syms):
                        sym = <unsigned int> syms[i]
                        existing = mapping.get(sym)
                        # prefer the lowest group, so that keysyms shared by more than one layout
                        # do not cause a group switch, then the lowest keycode / level within it:
                        if existing is None or existing[1] > <unsigned int> layout:
                            mapping[sym] = (<unsigned int> kc, <unsigned int> layout)
        self.keysym_to_keycode = mapping
        log("built keysym->keycode map with %i entries (keycodes %i..%i, %i group(s))",
            len(mapping), min_kc, max_kc, xkb_keymap_num_layouts(keymap))

    def get_keycode_for_keysym(self, keysym: int) -> tuple[int, int]:
        """ returns the (keycode, group) for this keysym, or (-1, 0) if the keymap has no such symbol """
        return self.keysym_to_keycode.get(int(keysym), (-1, 0))

    def get_keycode_for_keyname(self, name: str) -> tuple[int, int]:
        cdef xkb_keysym_t sym
        if not name:
            return -1, 0
        bname = name.encode("latin1")
        sym = xkb_keysym_from_name(bname, XKB_KEYSYM_NO_FLAGS)
        if sym == 0:
            return -1, 0
        return self.keysym_to_keycode.get(int(sym), (-1, 0))

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
