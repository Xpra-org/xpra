# This file is part of Xpra.
# Copyright (C) 2025 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.server.keyboard_config_base import KeyboardConfigBase
from xpra.util.objects import typedict
from xpra.log import Logger

log = Logger("wayland", "keyboard")


class KeyboardConfig(KeyboardConfigBase):
    """
    The whole seat shares a single `wlr_keyboard`, so this class only records
    the layout that one client asked for: installing it on the device belongs
    to the keyboard subsystem - see `WaylandKeyboardManager.install_keymap`.
    """
    __slots__ = ("layout", "layouts", "model", "variant", "variants", "options", "keys_pressed")

    def __init__(self):
        super().__init__()
        self.layout = ""
        self.model = ""
        self.variant = ""
        self.options = ""
        # the other layouts this client can switch to:
        self.layouts: tuple[str, ...] = ()
        self.variants: tuple[str, ...] = ()
        # this is shared between clients, see `KeyboardConnection.set_keymap`:
        self.keys_pressed: dict[int, Any] = {}

    def __repr__(self):
        return "wayland.KeyboardConfig(%s)" % "/".join(x for x in (self.layout, self.variant) if x)

    def get_info(self) -> dict[str, Any]:
        info = super().get_info()
        info |= {
            "layout": self.layout,
            "layouts": self.layouts,
            "model": self.model,
            "variant": self.variant,
            "variants": self.variants,
            "options": self.options,
        }
        return info

    def parse(self, props: typedict) -> int:
        # only used for the `keyboard-config` packet, which sends the attributes at the top level,
        # whereas the hello packet nests them all in a `keymap` dictionary:
        if "keymap" not in props:
            props = typedict({"keymap": dict(props)})
        return self.parse_layout(props) + self.parse_options(props)

    def parse_layout(self, props: typedict) -> int:
        """ used by both the hello packet and the `keyboard-config` packet """
        keymap = typedict(props.dictget("keymap")) or props
        # the keyboard model is only ever sent as part of `query_struct`:
        model = typedict(keymap.dictget("query_struct")).strget("model")
        mods = self.update_layout(keymap.strget("layout"), model,
                                  keymap.strget("variant"), keymap.strget("options"))
        layouts = keymap.strtupleget("layouts")
        variants = keymap.strtupleget("variants")
        if (layouts, variants) != (self.layouts, self.variants):
            self.layouts = layouts
            self.variants = variants
            mods += 1
        return mods

    def get_layout_groups(self) -> tuple[tuple[str, str], ...]:
        """
            The (layout, variant) pairs this client can use, active layout first.
            `layouts` and `variants` are paired by position, the way xkb pairs them,
            and a layout with no variant of its own simply gets an empty one.
            The active `layout` and `variant` are authoritative: a layout of the same
            name further down the list is that same layout, not another group.
        """
        groups: list[tuple[str, str]] = []
        if self.layout:
            groups.append((self.layout, self.variant))
        for i, layout in enumerate(self.layouts):
            if not layout or any(layout == name for name, _ in groups):
                continue
            groups.append((layout, self.variants[i] if i < len(self.variants) else ""))
        return tuple(groups)

    def set_layout(self, layout: str, variant: str, options: str) -> bool:
        # the legacy `layout-changed` packet does not carry the model
        return self.update_layout(layout, self.model, variant, options) > 0

    def update_layout(self, layout: str, model: str, variant: str, options: str) -> int:
        new = (layout, model, variant, options)
        old = (self.layout, self.model, self.variant, self.options)
        mods = sum(int(n != o) for n, o in zip(new, old))
        log("update_layout%s modified %i value(s), was %s", new, mods, old)
        self.layout, self.model, self.variant, self.options = new
        return mods

    def get_hash(self) -> str:
        """ this hash changes whenever a different keymap would have to be installed """
        groups = self.get_layout_groups()
        if not groups and not any((self.model, self.options)):
            return ""
        return "/".join(("+".join(f"{layout}:{variant}" for layout, variant in groups),
                         self.model, self.options))
