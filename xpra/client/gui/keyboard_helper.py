# This file is part of Xpra.
# Copyright (C) 2011 Serviware (Arthur Huillet, <ahuillet@serviware.com>)
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2008 Nathaniel Smith <njs@pobox.com>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Callable, Sequence

from xpra.keyboard.common import KeyEvent
from xpra.client.gui.keyboard_shortcuts_parser import parse_shortcut_modifiers, parse_shortcuts, get_modifier_names
from xpra.util.str_fn import std, csv, Ellipsizer
from xpra.util.env import envbool
from xpra.common import noop
from xpra.log import Logger

log = Logger("keyboard")

LAYOUT_GROUPS = envbool("XPRA_LAYOUT_GROUPS", True)
DEBUG_KEY_EVENTS = tuple(x.strip().lower() for x in os.environ.get("XPRA_DEBUG_KEY_EVENTS", "").split(",") if x.strip())


class KeyboardHelper:

    def __init__(self, net_send: Callable, keyboard_sync=True,
                 shortcut_modifiers="auto", key_shortcuts=(),
                 raw=False, backend="", model="", layout="", layouts=(),
                 variant="", variants=(), options=""):
        self.reset_state()
        self.send = net_send
        self.locked = False
        self.sync = keyboard_sync
        self.shortcuts_enabled = True
        self.shortcut_modifiers_str = shortcut_modifiers
        self.shortcut_modifiers: list[str] = []
        self.key_shortcuts_strs = key_shortcuts
        self.key_shortcuts: dict[str, list[str]] = {}
        # command line overrides:
        self.raw = raw
        self.backend = backend
        self.model_option = model
        self.layout_option = layout if (layout or "").lower() not in ("client", "auto") else ""
        self.variant_option = variant
        self.layouts_option = layouts
        self.variants_option = variants
        self.options = options
        # the platform class which allows us to map the keys:
        from xpra.platform.keyboard import Keyboard  # pylint: disable=import-outside-toplevel
        self.keyboard = Keyboard()  # pylint: disable=not-callable
        log("KeyboardHelper(%s) keyboard=%s",
            (net_send, keyboard_sync, key_shortcuts,
             raw, model, layout, layouts, variant, variants, options), self.keyboard)
        key_repeat = self.keyboard.get_keyboard_repeat()
        if key_repeat:
            self.key_repeat_delay, self.key_repeat_interval = key_repeat

    def set_platform_layout(self, layout: str) -> None:
        if hasattr(self.keyboard, "set_platform_layout"):
            self.keyboard.set_platform_layout(layout)

    def mask_to_names(self, mask) -> list[str]:
        return self.keyboard.mask_to_names(mask)

    def set_modifier_mappings(self, mappings: dict[str, str]):
        self.keyboard.set_modifier_mappings(mappings)

    def reset_state(self) -> None:
        self.keycodes: Sequence[tuple[int, str, int, int, int]] = ()
        self.x11_keycodes: dict[int, list[str]] = {}
        self.mod_meanings: dict[str, Any] = {}
        self.mod_managed: list[str] = []
        self.mod_pointermissing: list[str] = []
        self.backend = ""
        self.model = ""
        self.layout = ""
        self.layouts: list[str] = []
        self.variant = ""
        self.variants: list[str] = []
        self.options = ""
        self.backend = ""
        self.name = ""
        self.query = ""
        self.query_struct: dict[str, Any] = {}
        self.layout_groups = LAYOUT_GROUPS
        self.raw = False

        self.hash = None

        self.key_repeat_delay = -1
        self.key_repeat_interval = -1
        self.sync = False
        self.key_shortcuts = {}

    def cleanup(self) -> None:
        self.reset_state()
        self.send = noop

    def keymap_changed(self, *args) -> None:
        """ This method is overridden in the GTK Keyboard Helper """

    def parse_shortcuts(self) -> dict[str, list]:
        modifier_names = self.get_modifier_names()
        self.shortcut_modifiers = parse_shortcut_modifiers(self.shortcut_modifiers_str, modifier_names)
        self.key_shortcuts = parse_shortcuts(self.key_shortcuts_strs, self.shortcut_modifiers, modifier_names)
        return self.key_shortcuts

    def get_modifier_names(self) -> dict[str, str]:
        return get_modifier_names(self.mod_meanings)

    def key_handled_as_shortcut(self, window, key_name: str, modifiers: list[str], depressed: bool) -> bool:
        # find the shortcuts that may match this key:
        shortcuts = self.key_shortcuts.get(key_name)
        log("key_handled_as_shortcut%s shortcuts_enabled=%s, shortcuts=%s",
            (window, key_name, modifiers, depressed),
            self.shortcuts_enabled, shortcuts)
        if not self.shortcuts_enabled:
            return False
        if not shortcuts:
            return False
        if len(shortcuts) > 1:
            # sort shortcuts based on how many modifiers are required,
            # so that if multiple shortcuts use the same key,
            # we will try to match the one with the most modifiers first.
            # ie: Num_Lock+Menu will be tested before Menu
            # (this is needed because Num_Lock is then discarded when comparing the list of required modifiers!)
            shortcuts = sorted(shortcuts, key=lambda x: len(x[0]), reverse=True)
        for shortcut in shortcuts:
            if self._check_shortcut(window, key_name, modifiers, depressed, shortcut):
                return True
        return False

    def _check_shortcut(self, window, key_name: str, modifiers: list[str], depressed: bool, shortcut: Sequence) -> bool:
        req_mods, action, args = shortcut
        extra_modifiers = list(modifiers)
        for rm in req_mods:
            if rm not in modifiers:
                # modifier is missing, bail out
                log("not matched %s for %s: %s not in %s",
                    shortcut, key_name, rm, modifiers)
                return False
            try:
                extra_modifiers.remove(rm)
            except ValueError:
                pass  # same modifier listed twice?
        kmod, _, ignored = self.keyboard.get_keymap_modifiers()
        if not kmod and self.keyboard.modifier_keys:
            # fallback to server supplied map:
            kmod = self.keyboard.modifier_keys
        # ie: {'ISO_Level3_Shift': 'mod5', 'Meta_L': 'mod1', ...}
        log("keymap modifiers: %s", kmod)
        ignoremod = ("Caps_Lock", "Num_Lock")
        for x in ignoremod:
            mod = kmod.get(x)
            if mod in extra_modifiers:
                extra_modifiers.remove(mod)
        for mod in ignored:
            if mod in extra_modifiers:
                extra_modifiers.remove(mod)
        if extra_modifiers:
            log("skipping partial shortcut match %s, modifiers unmatched: %s", shortcut, extra_modifiers)
            return False
        log("matched shortcut %s", shortcut)
        if not depressed:
            # when the key is released, just ignore it - do NOT send it to the server!
            return True
        if action == "pass":
            return False
        try:
            method = getattr(window, action)
            log("key_handled_as_shortcut(%s,%s,%s,%s) found shortcut=%s, will call %s%s",
                window, key_name, modifiers, depressed, shortcut, method, args)
        except AttributeError as e:
            log.error("key dropped, invalid method name in shortcut %s: %s", action, e)
            return True
        try:
            method(*args)
            log("key_handled_as_shortcut(%s,%s,%s,%s) has been handled: %s",
                window, key_name, modifiers, depressed, method)
        except Exception:
            log.error("Error: key_handled_as_shortcut(%s,%s,%s,%s)", window, key_name, modifiers, depressed)
            log.error(" failed to execute shortcut=%s", shortcut)
            log.error("", exc_info=True)
        return True

    def process_key_event(self, wid: int, key_event: KeyEvent) -> bool:
        """
            This method gives the Keyboard class
            a chance to fire more than one send_key_action.
            (win32 uses this for AltGr emulation)
        """
        self.keyboard.process_key_event(self.send_key_action, wid, key_event)
        return False

    def debug_key_event(self, wid: int, key_event: KeyEvent) -> None:
        if not DEBUG_KEY_EVENTS:
            return

        def keyname(v: str) -> str:
            if v.endswith("_L") or v.endswith("_R"):
                return v[:-2].lower()
            return v.lower()

        def dbg(v) -> bool:
            return v and keyname(v) in DEBUG_KEY_EVENTS

        debug = ("all" in DEBUG_KEY_EVENTS) or dbg(key_event.keyname) or dbg(key_event.string)
        modifiers = key_event.modifiers
        if not debug and modifiers:
            # see if one of the modifier matches:
            # either the raw name (ie: "mod2") or its actual meaning (ie: "NumLock")
            for m in modifiers:
                if m in DEBUG_KEY_EVENTS:
                    debug = True
                    break
                name = keyname(self.keyboard.modifier_names.get(m) or "")
                if name and name in DEBUG_KEY_EVENTS:
                    debug = True
                    break
        if debug:
            log.info("key event %s on window %i", key_event, wid)

    def send_key_action(self, wid: int, key_event: KeyEvent) -> None:
        log("send_key_action(%s, %s)", wid, key_event)
        packet = ["key-action", wid]
        for x in ("keyname", "pressed", "modifiers", "keyval", "string", "keycode", "group"):
            packet.append(getattr(key_event, x))
        self.debug_key_event(wid, key_event)
        self.send(*packet)

    def get_layout_spec(self) -> tuple[str, str, Sequence[str], str, Sequence[str], str]:
        """ add / honour overrides """
        model, layout, layouts, variant, variants, options = self.keyboard.get_layout_spec()
        log("%s.get_layout_spec()=%s", self.keyboard, (layout, layouts, variant, variants, options))

        def inl(v, l) -> list:
            try:
                if v in l or v is None:
                    return l
                return [v] + list(l)
            except Exception:
                if v is not None:
                    return [v]
                return []

        layout = self.layout_option or layout
        layouts = inl(layout, self.layouts_option or layouts)
        variant = self.variant_option or variant
        variants = inl(variant, self.variants_option or variants)
        val = (
            self.model_option or model,
            layout,
            layouts,
            variant,
            variants,
            self.options or options,
        )
        log("get_layout_spec()=%s", val)
        return val

    def get_keymap_spec(self) -> dict[str, Any]:
        query_struct = self.keyboard.get_keymap_spec()
        if query_struct:
            if self.backend:
                query_struct["backend"] = self.backend
            if self.model_option:
                query_struct["model"] = self.model_option
            if self.layout_option:
                query_struct["layout"] = self.layout_option
            if self.layouts_option:
                query_struct["layouts"] = csv(self.layouts_option)
            if self.variant_option:
                query_struct["variant"] = self.variant_option
            if self.variants_option:
                query_struct["variants"] = csv(self.variants_option)
            if self.options:
                if self.options.lower() == "none":
                    query_struct["options"] = ""
                else:
                    query_struct["options"] = self.options
        return query_struct

    def query_xkbmap(self) -> None:
        log("query_xkbmap()")
        self.model, self.layout, self.layouts, self.variant, self.variants, self.options = self.get_layout_spec()
        self.query_struct = self.get_keymap_spec()
        log(f"query_xkbmap() query_struct={self.query_struct}")
        self.keycodes = self.get_full_keymap()
        log(f"query_xkbmap() keycodes={self.keycodes}")
        self.x11_keycodes = self.keyboard.get_x11_keymap()
        log(f"query_xkbmap() {self.keyboard}.get_x11_keymap()={self.x11_keycodes}")
        mods = self.keyboard.get_keymap_modifiers()
        self.mod_meanings, self.mod_managed, self.mod_pointermissing = mods
        log(f"query_xkbmap() get_keymap_modifiers()={mods}")
        self.update_hash()
        log(f"layout={self.layout}, layouts={self.layouts}, variant={self.variant}, variants={self.variants}")
        log(f"query-struct={self.query_struct}")
        log("keycodes=%s", Ellipsizer(self.keycodes))
        log("x11 keycodes=%s", Ellipsizer(self.x11_keycodes))
        log(f"mod managed: {self.mod_managed}")
        log(f"mod meanings: {self.mod_meanings}")
        log(f"mod pointermissing: {self.mod_pointermissing}")
        log(f"hash={self.hash}")

    def update(self) -> None:
        if not self.locked:
            self.query_xkbmap()
            self.parse_shortcuts()

    def layout_str(self) -> str:
        if self.backend and self.name:
            return f"{self.backend} {self.name!r}"
        return " / ".join(str(x) for x in (
            self.layout_option or self.layout, self.variant_option or self.variant) if bool(x))

    def send_layout(self) -> None:
        log("send_layout() layout_option=%r, layout=%r, variant_option=%r, variant=%r, options=%r",
            self.layout_option, self.layout, self.variant_option, self.variant, self.options)
        log(f"send_layout() backend={self.backend!r}, name={self.name!r}")
        self.send("layout-changed",
                  self.layout_option or self.layout or "",
                  self.variant_option or self.variant or "",
                  self.options or "",
                  self.backend or "", self.name or "")

    def send_keymap(self) -> None:
        log("send_keymap()")
        props = {"keymap": self.get_keymap_properties()}
        self.send("keymap-changed", props)

    def update_hash(self) -> None:
        import hashlib
        h = hashlib.sha256()

        def hashadd(v) -> None:
            h.update(("/%s" % str(v)).encode("utf8"))

        for x in (self.mod_meanings, self.mod_pointermissing, self.keycodes, self.x11_keycodes):
            hashadd(x)
        if self.query_struct:
            # flatten the dict in a predicatable order:
            for k in sorted(self.query_struct.keys()):
                hashadd(self.query_struct.get(k))
        self.hash = "/".join([str(x) for x in (self.layout, self.variant, h.hexdigest()) if bool(x)])

    def get_full_keymap(self) -> Sequence[tuple[int, str, int, int, int]]:
        return ()

    def get_keymap_properties(self, skip=()) -> dict[str, Any]:
        props = {}
        for x in (
                "backend", "layout", "layouts", "variant", "variants",
                "raw", "layout_groups",
                "sync",
                "query_struct", "mod_meanings",
                "mod_managed", "mod_pointermissing", "keycodes", "x11_keycodes",
        ):
            if x in skip:
                continue
            v = getattr(self, x)
            if v:
                props[x] = v
        return props

    def log_keyboard_info(self) -> None:
        # show the user a summary of the settings used
        # (values detected with overrides applied)
        model, layout, _, variant, _, options = self.get_layout_spec()
        kb_info = {
            "model": model,
            "layout": layout,
            "variant": variant,
            "options": options,
        }
        if self.backend:
            kb_info["backend"] = self.backend
        if self.query_struct:
            kb_info["rules"] = self.query_struct.get("rules", "")
        if not kb_info:
            log.info(" using default keyboard settings")
        else:
            log.info(" keyboard settings: %s", csv(f"{k}={std(v)}" for k, v in kb_info.items() if v))
