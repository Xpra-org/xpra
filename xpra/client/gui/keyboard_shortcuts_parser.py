# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections.abc import Sequence

from xpra.util.str_fn import csv
from xpra.os_util import POSIX, OSX, WIN32
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, DEFAULT_MODIFIER_NUISANCE
from xpra.util.parsing import TRUE_OPTIONS, FALSE_OPTIONS
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


def get_modifier_labels(modifier_names: dict[str, str]) -> dict[str, str]:
    """
    maps the internal modifier names (ie: "mod1") to the name of the key the user presses (ie: "Alt"),
    `modifier_names` is the reverse mapping, as returned by `get_modifier_names()`
    """
    labels: dict[str, str] = {}
    for key_name, mod_name in modifier_names.items():
        # the first key name found wins, ie: "alt" over "meta" for "mod1":
        if mod_name in labels:
            continue
        if key_name == "altgr":
            text = "AltGr"
        elif key_name == "super" and WIN32:
            text = "Win"
        else:
            text = key_name.capitalize()
        labels[mod_name] = text
    return labels


def shortcut_keys_str(keyname: str, modifiers: Sequence[str], mod_labels: dict[str, str]) -> str:
    # ie: "Alt+Shift+F1"
    return "+".join([mod_labels.get(mod, mod) for mod in modifiers] + [keyname])


def shortcut_action_str(action: str, args: Sequence) -> str:
    # ie: "show_menu" or "scaleup(2)"
    if args:
        return "%s(%s)" % (action, csv(args))
    return action


def parse_shortcut_modifiers(s: str, modifier_names: dict[str, str], swap_keys: bool = False) -> list[str]:
    # figure out the default shortcut modifiers
    # accept "," or "+" as delimiter:
    shortcut_modifiers = s.lower().replace(",", "+").split("+")

    def mod_defaults() -> list[str]:
        mods = ["meta", "shift"]
        if OSX:
            # use the Command key, which is reported as "control" when swapping keys:
            if swap_keys:
                mods = ["control", "shift"]
        elif POSIX:
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
                log.warn("Warning: invalid shortcut modifier %r", x)
            else:
                r.append(x)
        if shortcut_modifiers and not r:
            log.warn(" using defaults instead")
            shortcut_modifiers = mod_defaults()
        else:
            shortcut_modifiers = r
    log("shortcut modifiers=%s", shortcut_modifiers)
    return shortcut_modifiers


def parse_args(str_args: str) -> list[str | float | bool | int | None]:
    args = []
    for x in str_args.split(","):
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
    return args


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
                args = parse_args(all_args)
            except Exception as e:
                log.warn("Warning: failed to parse arguments of shortcut:")
                log.warn(" %r: %s", s, e)
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
                modname = modifier_names.get(mod, "")
                if not modname:
                    log.warn("Warning: invalid modifier %r in keyboard shortcut %r", mod, s)
                    log.warn(" the modifiers must be one of: %s", csv(modifier_names.keys()))
                    valid = False
                    break
                modifiers.append(modname)
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
    if log.is_debug_enabled():
        # show the keys the user presses, ie: "Alt" rather than "mod1":
        mod_labels = get_modifier_labels(modifier_names)
        for keyname, key_shortcuts in shortcuts.items():
            for modifiers, action, args in key_shortcuts:
                log("* %-32s: %s", shortcut_keys_str(keyname, modifiers, mod_labels), shortcut_action_str(action, args))
    return shortcuts
