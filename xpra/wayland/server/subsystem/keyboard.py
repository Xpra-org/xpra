# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from collections.abc import Sequence

from xpra.server.subsystem.keyboard import KeyboardManager
from xpra.server.source.keyboard import KeyboardConnection
from xpra.util.objects import typedict
from xpra.util.str_fn import csv
from xpra.log import Logger

log = Logger("server", "wayland")

# xkb silently truncates a keymap to its first 4 layouts:
MAX_LAYOUT_GROUPS = 4


class WaylandKeyboardManager(KeyboardManager):
    __slots__ = ()
    BACKEND = "wayland"

    def make_keyboard_device(self):
        return self.server.compositor.get_keyboard_device()

    def get_keyboard_config(self, props=None):
        from xpra.wayland.server.keyboard_config import KeyboardConfig
        keyboard_config = KeyboardConfig()
        p = typedict(props or {})
        keyboard_config.enabled = p.boolget("keyboard", True)
        keyboard_config.parse(p)
        log("get_keyboard_config(%s)=%s", props, keyboard_config)
        return keyboard_config

    def set_keymap(self, server_source, force=False) -> None:
        if getattr(server_source, "effective_readonly", lambda: self.server.readonly)():
            return
        log("set_keymap(%s, %s) current config=%s", server_source, force, self.config)
        server_source.set_keymap(self.config, self.config_hash, self.keys_pressed, force)
        self.set_current_config(server_source.keyboard_config)

    def set_current_config(self, config) -> None:
        # the config we record as current is the one installed on the seat,
        # so only install a keymap when the recorded hash actually changes:
        installed = self.config_hash
        super().set_current_config(config)
        if config and config.enabled and self.config_hash != installed:
            self.install_keymap(config)

    def get_layout_groups(self, config) -> tuple[tuple[str, str], ...]:
        # the whole seat shares a single `wlr_keyboard`, so its keymap has to carry
        # the layouts of every keyboard client: the one being configured owns the first
        # group and the others follow, which is what lets `get_keycode` below find a
        # symbol that only exists in another client's layout
        groups = list(config.get_layout_groups())
        for ss in self.get_sources_by_type(KeyboardConnection):
            other = getattr(ss, "keyboard_config", None)
            if other is None or other is config or not other.enabled:
                continue
            for group in other.get_layout_groups():
                if group not in groups:
                    groups.append(group)
        if len(groups) > MAX_LAYOUT_GROUPS:
            log.info("Warning: only the first %i keyboard layouts can be used", MAX_LAYOUT_GROUPS)
            log.info(" dropping %s", csv(f"{layout!r}" for layout, _ in groups[MAX_LAYOUT_GROUPS:]))
            groups = groups[:MAX_LAYOUT_GROUPS]
        return tuple(groups)

    def install_keymap(self, config) -> None:
        if not self.device:
            return
        groups = self.get_layout_groups(config) or (("us", ""), )
        # xkb pairs the layouts and variants by position,
        # so the variant list must always have one entry per layout:
        layouts = ",".join(layout for layout, _ in groups)
        variants = ",".join(variant for _, variant in groups)
        model = config.model or "pc105"
        log("install_keymap(%s) layouts=%r, model=%r, variants=%r, options=%r",
            config, layouts, model, variants, config.options)
        if self.device.set_layout(layouts, model, variants, config.options) or len(groups) <= 1:
            return
        # a single unusable layout stops the whole keymap from compiling,
        # so fall back to the one belonging to the client we are configuring:
        layout, variant = groups[0]
        log.info("retrying with just the %r layout", layout)
        self.device.set_layout(layout, model, variant, config.options)

    def get_keycode(self, ss, client_keycode: int, keyname: str,
                    pressed: bool, modifiers: list, keyval: int, keystr: str, group: int):
        # The Wayland virtual keyboard uses its own xkb keymap, so neither the client's keycode
        # (from a foreign keymap, e.g. Win32 VK codes) nor its group (which indexes that keymap's
        # layouts) is meaningful here: we resolve the keysym against the keymap we installed and
        # return the group *that* keymap puts it in, which the caller applies before pressing.
        # The xkb keymap uses X11-style keycodes (evdev + 8) and `press_key` subtracts 8
        # before handing them to wlroots, so we just return what the keymap gives us.
        keycode = -1
        keymap_group = 0
        if self.device:
            if keyval > 0:
                keycode, keymap_group = self.device.get_keycode_for_keysym(keyval)
            if keycode < 0 and keyname:
                keycode, keymap_group = self.device.get_keycode_for_keyname(keyname)
        if keycode > 0:
            log("get_keycode: keyname=%r keyval=%i client_keycode=%i, group=%i -> xkb keycode=%i, group=%i",
                keyname, keyval, client_keycode, group, keycode, keymap_group)
            return keycode, keymap_group
        log("get_keycode: no xkb mapping for keyname=%r keyval=%i, falling back",
            keyname, keyval)
        return super().get_keycode(ss, client_keycode, keyname, pressed, modifiers, keyval, keystr, group)

    def fake_key(self, keycode: int, press: bool) -> None:
        log("fake_key(%i, %s)", keycode, press)
        if self.device:
            self.device.reapply_modifiers()
        super().fake_key(keycode, press)
        self.server.compositor.flush()

    def update_keyboard_modifiers(self, modifiers: Sequence[str], group: int = -1) -> None:
        if group < 0 and self.device:
            group = self.device.get_layout_group()
        if self.device:
            self.device.update_modifiers(modifiers, group)

    def do_process_keyboard_event(self, proto, wid: int, keyname: str, pressed: bool, kattrs: dict) -> None:
        attrs = typedict(kattrs)
        if "modifiers" in kattrs:
            # the client's group indexes its own keymap, so keep the group we are on:
            # `get_keycode` resolves the one this key actually needs, and the superclass
            # applies it through `set_keyboard_layout_group` before pressing the key
            self.update_keyboard_modifiers(attrs.strtupleget("modifiers", ()))
        super().do_process_keyboard_event(proto, wid, keyname, pressed, kattrs)

    def set_keyboard_layout_group(self, grp: int) -> None:
        if self.device:
            self.device.set_layout_group(grp)
