# This file is part of Xpra.
# Copyright (C) 2010-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.util.str_fn import csv, print_nested_dict
from xpra.os_util import POSIX
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE
from xpra.scripts.config import TRUE_OPTIONS, FALSE_OPTIONS
from xpra.log import Logger

log = Logger("keyboard")


def get_modifier_names(mod_meanings: dict[str, str]) -> dict[str, str]:
    # modifier names contains the internal modifiers list, ie: "mod1", "control", ...
    # but the user expects the name of the key to be used, ie: "alt" or "super"
    # whereas at best, we keep "Alt_L" : "mod1" mappings... (posix)
    # so generate a map from one to the other:
    modifier_names: dict[str, str] = {}
    meanings = mod_meanings or DEFAULT_MODIFIER_MEANINGS
    DEFAULT_MODIFIER_IGNORE_KEYNAMES = ["Caps_Lock", "Num_Lock", "Scroll_Lock"]
    for pub_name, mod_name in meanings.items():
        if mod_name in DEFAULT_MODIFIER_NUISANCE or pub_name in DEFAULT_MODIFIER_IGNORE_KEYNAMES:
            continue
        # just hope that xxx_L is mapped to the same modifier as xxx_R!
        if pub_name.endswith("_L") or pub_name.endswith("_R"):
            pub_name = pub_name[:-2]
        elif pub_name == "ISO_Level3_Shift":
            pub_name = "AltGr"
        if pub_name not in modifier_names:
            modifier_names[pub_name.lower()] = mod_name
        if pub_name.lower() == "control":
            # alias "control" to "ctrl" as it is often used:
            modifier_names["ctrl"] = mod_name
    log("parse_shortcuts: modifier names=%s", modifier_names)
    return modifier_names


def parse_shortcut_modifiers(s: str, modifier_names: dict[str, str]) -> list[str]:
    # figure out the default shortcut modifiers
    # accept "," or "+" as delimiter:
    shortcut_modifiers = s.lower().replace(",", "+").split("+")

    def mod_defaults():
        mods = ["meta", "shift"]
        if POSIX:
            # gnome intercepts too many of the Alt+Shift shortcuts,
            # so use control with gnome:
            if os.environ.get("XDG_CURRENT_DESKTOP") == "GNOME":
                mods = ["control", "shift"]
        return mods

    if shortcut_modifiers == ["auto"]:
        shortcut_modifiers = mod_defaults()
    elif shortcut_modifiers == ["none"]:
        shortcut_modifiers = []
    else:
        r = []
        for x in shortcut_modifiers:
            x = x.lower()
            if x not in modifier_names:
                log.warn("Warning: invalid shortcut modifier '%s'", x)
            else:
                r.append(x)
        if shortcut_modifiers and not r:
            log.warn(" using defaults instead")
            shortcut_modifiers = mod_defaults()
        else:
            shortcut_modifiers = r
    log("shortcut modifiers=%s", shortcut_modifiers)
    return shortcut_modifiers


def parse_shortcuts(strs: Sequence[str],
                    shortcut_modifiers: Sequence[str],
                    modifier_names: dict[str, str],
                    ) -> dict[str, list[tuple[list[str], str, list[str | float | bool | int | None]]]]:
    """
    if none are defined, add this as default
    it would be nicer to specify it via OptionParser in main,
    but then it would always have to be there with no way of removing it
    whereas now it is enough to define one (any shortcut)
    """
    if not strs:
        strs = ["meta+shift+F4:quit"]
    log("parse_shortcuts(%s)", strs)
    shortcuts: dict[str, list[tuple[list[str], str, list[str | float | bool | int | None]]]] = {}
    # figure out the default shortcut modifiers
    # accept "," or "+" as delimiter:
    for s in strs:
        if s == "none":
            continue
        if s == "clear":
            shortcuts = {}
            continue
        # example for s: Control+F8:some_action()
        if s.find("=") > s.find(":"):
            parts = s.split("=", 1)
        else:
            parts = s.split(":", 1)
        if len(parts) != 2:
            log.error("Error: invalid key shortcut '%s'", s)
            continue
        # example for action: "quit"
        action = parts[1].strip()
        args: list[str | float | bool | int | None] = []
        if action.find("(") > 0 and action.endswith(")"):
            try:
                action, all_args = action[:-1].split("(", 1)
                for x in all_args.split(","):
                    x = x.strip()
                    if not x:
                        continue
                    if (x[0] == '"' and x[-1] == '"') or (x[0] == "'" and x[-1] == "'"):
                        args.append(x[1:-1])
                    elif x == "None":
                        args.append(None)
                    elif x.find(".") != -1:
                        args.append(float(x))
                    elif x.lower() in TRUE_OPTIONS:
                        args.append(True)
                    elif x.lower() in FALSE_OPTIONS:
                        args.append(False)
                    else:
                        args.append(int(x))
            except Exception as e:
                log.warn("Warning: failed to parse arguments of shortcut:")
                log.warn(" '%s': %s", s, e)
                continue
        action = action.replace("-", "_")  # must be an object attribute
        log("action(%s)=%s%s", s, action, args)
        # example for keyspec: ["Alt", "F8"]
        keyspec = parts[0].split("+")
        modifiers = []
        if len(keyspec) > 1:
            valid = True
            # ie: ["Alt"]
            for mod in keyspec[:len(keyspec) - 1]:
                mod = mod.lower()
                if mod == "none":
                    continue
                if mod == "#":
                    # this is the placeholder for the list of shortcut modifiers:
                    for x in shortcut_modifiers:
                        imod = modifier_names.get(x)
                        if imod:
                            modifiers.append(imod)
                    continue
                # find the real modifier for this name:
                # ie: "alt_l" -> "mod1"
                imod = modifier_names.get(mod)
                if not imod:
                    log.warn("Warning: invalid modifier '%s' in keyboard shortcut '%s'", mod, s)
                    log.warn(" the modifiers must be one of: %s", csv(modifier_names.keys()))
                    valid = False
                    break
                modifiers.append(imod)
            if not valid:
                continue
        # should we be validating the keyname?
        keyname = keyspec[len(keyspec) - 1]
        key_shortcuts: list[tuple[list[str], str, list[str | float | bool | int | None]]] = shortcuts.get(keyname, [])
        # remove any existing action using the same modifiers:
        key_shortcuts = [x for x in key_shortcuts if x[0] != modifiers]
        if action != "_":
            key_shortcuts.append((modifiers, action, args))
        shortcuts[keyname] = key_shortcuts
        log("shortcut(%s)=%s", s, csv((modifiers, action, args)))
    log("parse_shortcuts(%s)=%s", strs, shortcuts)
    print_nested_dict(shortcuts, print_fn=log)
    return shortcuts
