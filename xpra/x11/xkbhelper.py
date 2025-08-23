# This file is part of Xpra.
# Copyright (C) 2011 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any
from collections.abc import Iterable, Sequence

from xpra.common import noop
from xpra.keyboard.mask import DEFAULT_MODIFIER_MEANINGS, MODIFIER_MAP
from xpra.util.objects import typedict
from xpra.util.str_fn import std, csv, bytestostr, Ellipsizer
from xpra.util.env import envbool
from xpra.x11.error import xsync, xlog
from xpra.x11.bindings.keyboard import X11KeyboardBindings
from xpra.log import Logger

log = Logger("x11", "keyboard")
verboselog = Logger("x11", "keyboard", "verbose")

XKB = envbool("XPRA_XKB", True)

DEFAULT_RULES = os.environ.get("XKB_DEFAULT_RULES", "evdev")
DEFAULT_MODEL = os.environ.get("XKB_DEFAULT_MODEL", "pc105")
DEFAULT_LAYOUT = os.environ.get("XKB_DEFAULT_LAYOUT", "us")
DEFAULT_VARIANT = os.environ.get("XKB_DEFAULT_VARIANT", "")
DEFAULT_OPTIONS = os.environ.get("XKB_DEFAULT_OPTIONS", "")

DEBUG_KEYSYMS = [x for x in os.environ.get("XPRA_DEBUG_KEYSYMS", "").split(",") if len(x) > 0]

# keys we choose not to map if the free space in the keymap is too limited
# this list was generated using:
# $ DISPLAY=:1 xmodmap -pke | awk -F= '{print $2}' | xargs -n 1 echo | sort -u | grep XF | xargs
OPTIONAL_KEYS = [
    "XF86AudioForward", "XF86AudioLowerVolume", "XF86AudioMedia", "XF86AudioMicMute", "XF86AudioMute",
    "XF86AudioNext", "XF86AudioPause", "XF86AudioPlay", "XF86AudioPrev", "XF86AudioRaiseVolume",
    "XF86AudioRecord", "XF86AudioRewind", "XF86AudioStop",
    "XF86Back", "XF86Battery", "XF86Bluetooth", "XF86Calculator", "XF86ClearGrab", "XF86Close",
    "XF86Copy", "XF86Cut", "XF86Display", "XF86Documents", "XF86DOS", "XF86Eject", "XF86Explorer",
    "XF86Favorites", "XF86Finance", "XF86Forward", "XF86Game", "XF86Go", "XF86HomePage", "XF86KbdBrightnessDown",
    "XF86KbdBrightnessUp", "XF86KbdLightOnOff",
    "XF86Launch1", "XF86Launch2", "XF86Launch3", "XF86Launch4", "XF86Launch5", "XF86Launch6",
    "XF86Launch7", "XF86Launch8", "XF86Launch9", "XF86LaunchA", "XF86LaunchB",
    "XF86Mail", "XF86MailForward", "XF86MenuKB", "XF86Messenger", "XF86MonBrightnessDown",
    "XF86MonBrightnessUp", "XF86MyComputer",
    "XF86New", "XF86Next_VMode", "XF86Open", "XF86Paste", "XF86Phone", "XF86PowerOff",
    "XF86Prev_VMode", "XF86Reload", "XF86Reply", "XF86RotateWindows", "XF86Save", "XF86ScreenSaver",
    "XF86ScrollDown", "XF86ScrollUp", "XF86Search", "XF86Send", "XF86Shop", "XF86Sleep", "XF86Suspend",
    "XF86Switch_VT_1", "XF86Switch_VT_10", "XF86Switch_VT_11", "XF86Switch_VT_12", "XF86Switch_VT_2", "XF86Switch_VT_3",
    "XF86Switch_VT_4", "XF86Switch_VT_5", "XF86Switch_VT_6", "XF86Switch_VT_7", "XF86Switch_VT_8", "XF86Switch_VT_9",
    "XF86Tools", "XF86TouchpadOff", "XF86TouchpadOn", "XF86TouchpadToggle", "XF86Ungrab", "XF86WakeUp", "XF86WebCam",
    "XF86WLAN", "XF86WWW", "XF86Xfer",
]


def clean_keyboard_state() -> None:
    X11Keyboard = X11KeyboardBindings()
    with xlog:
        X11Keyboard.ungrab_all_keys()
    with xlog:
        X11Keyboard.set_layout_group(0)
    keycodes = {}
    with xlog:
        keycodes = X11Keyboard.get_keycodes_down()
    if keycodes:
        with xlog:
            try:
                from xpra.x11.bindings.test import XTestBindings
            except ImportError:
                pass
            else:
                XTest = XTestBindings()
                XTest.unpress_keys(tuple(keycodes.keys()))


################################################################################
# keyboard layouts


def do_set_keymap(layout: str, variant: str, options, query_struct) -> None:
    """
        layout is the generic layout name (used on non posix platforms)
            defaults to `us`
        variant is the layout variant (optional)
        query_struct is the output of `setxkbmap -query` on the client
        parsed into a dictionary
        Use those to try to set up the correct keyboard map for the client
        so that all the keycodes sent will be mapped
    """
    # First we try to use data from setxkbmap -query,
    # preferably as structured data:
    query_struct = typedict(query_struct)
    rules = DEFAULT_RULES
    model = DEFAULT_MODEL
    layout = layout or DEFAULT_LAYOUT
    if query_struct:
        log("do_set_keymap using xkbmap_query struct=%s", query_struct)
        # The query_struct data will look something like this:
        #    {
        #    b"rules"       : b"evdev",
        #    b"model"       : b"pc105",
        #    b"layout"      : b"gb",
        #    b"options"     : b"grp:shift_caps_toggle",
        #    }
        # parse the data into a dict:
        rules = query_struct.strget("rules", DEFAULT_RULES)
        model = query_struct.strget("model", DEFAULT_MODEL)
        layout = query_struct.strget("layout", DEFAULT_LAYOUT)
        variant = query_struct.strget("variant", DEFAULT_VARIANT)
        options = query_struct.strget("options", DEFAULT_OPTIONS)
        if layout:
            log.info("setting keymap: %s",
                     csv(f"{k}={std(v)}" for k, v in {
                         "rules": rules,
                         "model": model,
                         "layout": layout,
                         "variant": variant,
                         "options": options,
                     }.items() if v))
            if safe_setxkbmap(rules, model, layout, variant, options):
                return
        else:
            if safe_setxkbmap(rules, model, "", "", ""):
                return
    # fallback for non X11 clients:
    log.info("setting keyboard layout to %r", std(layout))
    safe_setxkbmap(rules, model, layout, variant, options)


def safe_setxkbmap(rules: str, model: str, layout: str, variant: str, options: str):
    # (we execute the options separately in case that fails..)
    X11Keyboard = X11KeyboardBindings()
    try:
        if X11Keyboard.setxkbmap(rules, model, layout, variant, options):
            return True
    except Exception:
        log("safe_setxkbmap%s", (rules, model, layout, variant, options), exc_info=True)
        log.warn("Warning: failed to set exact keymap,")
        log.warn(f" {rules=}, {model=}, {layout=}, {variant=}, {options=}")
    if options:
        # try again with no options:
        try:
            X11Keyboard.setxkbmap(rules, model, layout, variant, "")
            return True
        except Exception:
            log("setxkbmap", exc_info=True)
            log.error("Error: failed to set exact keymap")
            log.error(" even without applying any options..")
    return False

################################################################################
# keycodes


def apply_xmodmap(instructions: list[tuple]) -> list[tuple]:
    try:
        X11Keyboard = X11KeyboardBindings()
        with xsync:
            unset = X11Keyboard.set_xmodmap(instructions)
    except Exception as e:
        log("apply_xmodmap(%s)", instructions, exc_info=True)
        log.error("Error configuring modifier map: %s", e)
        unset = instructions
    if unset is None:
        # None means an X11 error occurred, re-do all:
        unset = instructions
    return unset


def get_keycode_mappings() -> dict[int, list[str]]:
    X11Keyboard = X11KeyboardBindings()
    if XKB and X11Keyboard.hasXkb():
        return X11Keyboard.get_xkb_keycode_mappings()
    return X11Keyboard.get_keycode_mappings()


def get_keyval_mappings() -> dict[int, dict[int, Sequence[int]]]:
    X11Keyboard = X11KeyboardBindings()
    if XKB and X11Keyboard.hasXkb():
        return X11Keyboard.get_xkb_keysym_mappings()
    return {}


def set_keycode_translation(xkbmap_x11_keycodes: dict, xkbmap_keycodes: Iterable) -> dict[str | tuple[int, str], int]:
    x11_keycodes = get_keycode_mappings()
    keycodes: dict[int, set]
    if xkbmap_x11_keycodes:
        dump_dict(xkbmap_x11_keycodes)
        keycodes = indexed_mappings(xkbmap_x11_keycodes)
    else:
        keycodes = gtk_keycodes_to_mappings(xkbmap_keycodes)
    log("set_keycode_translation(%s, %s)", Ellipsizer(xkbmap_x11_keycodes), Ellipsizer(xkbmap_keycodes))
    log(" keycodes=%s", Ellipsizer(keycodes))
    log(" x11_keycodes=%s", Ellipsizer(x11_keycodes))
    verboselog("set_keycode_translation(%s, %s)", xkbmap_x11_keycodes, xkbmap_keycodes)
    verboselog(" keycodes=%s", keycodes)
    verboselog(" x11_keycodes=%s", x11_keycodes)
    """
    Example data:
    ```
    keycodes = {
        9: set([('', 1), ('Escape', 4), ('', 3), ('Escape', 0), ('Escape', 2)]),
        10: set([('onesuperior', 4), ('onesuperior', 8), ('exclam', 1), ('1', 6),
                 ('exclam', 3), ('1', 2), ('exclamdown', 9), ('exclamdown', 5), ('1', 0), ('exclam', 7)]),

    x11_keycodes = {
       8: ['Mode_switch', '', 'Mode_switch', '', 'Mode_switch'],
       9: ['Escape', '', 'Escape', '', 'Escape'],
       }
    ```
    create faster lookup table:
    """
    trans = do_set_keycode_translation(keycodes)

    if not xkbmap_x11_keycodes:
        # now add all the keycodes we may not have mapped yet
        # (present in the `x11_keycodes` mappings but not the `trans`lation table)
        for keycode, keysyms in x11_keycodes.items():
            for i, keysym in enumerate(keysyms):
                if keysym in DEBUG_KEYSYMS:
                    log.info("x11 keycode %s: %s", keycode, keysym)
                # record under `keysym` and also `(keysym, index)`:
                for trans_key in (keysym, (keysym, i)):
                    if trans_key not in trans:
                        trans[trans_key] = keycode
    log("set_keycode_translation(..)=%s", Ellipsizer(trans))
    verboselog("set_keycode_translation(..)=%s", trans)
    return trans


def do_set_keycode_translation(keycodes: dict[int, set]) -> dict[str | tuple[int, str], int]:
    """
        Translate the given keycodes into a keymap,
        and try to preserve the existing keymap
    """
    x11_keycodes = get_keycode_mappings()
    # create faster keysym lookup table:
    x11_keycodes_for_keysym: dict[str, set[int]] = {}
    for keycode, keysyms in x11_keycodes.items():
        for keysym in keysyms:
            x11_keycodes_for_keysym.setdefault(keysym, set()).add(keycode)

    def find_keycode(kc: int, keysym, i: int) -> tuple:
        keycodes = tuple(x11_keycodes_for_keysym.get(keysym, set()))
        if not keycodes:
            return ()

        rlog = noop
        debug_keysym = keysym in DEBUG_KEYSYMS
        if debug_keysym:
            log.info("set_keycode_translation: find_keycode%s x11 keycodes=%s", (kc, keysym, i), keycodes)

            def ilog(keycode, msg) -> None:
                log.info("set_keycode_translation: find_keycode%s=%s (%s)", (kc, keysym, i), keycode, msg)
            rlog = ilog

        # no other option, use it:
        for keycode in keycodes:
            defs = x11_keycodes.get(keycode)
            if debug_keysym:
                log.info("server x11 keycode %i: %s", keycode, defs)
            if not defs:
                raise RuntimeError(f"bug: keycode {keycode} not found in {x11_keycodes}")
            if len(defs) > i and defs[i] == keysym:
                rlog(keycode, "exact index match")
                return keycode, True
        # if possible, use the same one:
        if kc in keycodes:
            rlog(kc, "using same keycode as client")
            return kc, False
        keycode = keycodes[0]
        rlog(keycode, "using first match")
        return keycode, False

    # generate the translation map:
    trans: dict[str | tuple[int, str] | tuple[str, int], int] = {}
    for keycode, defs in keycodes.items():
        if bool(set(DEBUG_KEYSYMS) & set(bytestostr(d[0]) for d in defs)):
            log.info("client keycode=%i, defs=%s", keycode, defs)
        for bkeysym, i in tuple(defs):             # ie: (b'1', 0) or (b'A', 1), etc
            keysym = bytestostr(bkeysym)
            m = find_keycode(keycode, keysym, i)
            if not m:
                continue
            x11_keycode, index_matched = m
            trans[(keycode, keysym)] = x11_keycode
            trans[keysym] = x11_keycode
            if index_matched:
                trans[(keysym, i)] = x11_keycode
    return trans


def get_keysym_to_modifier_map(modifiers: dict[str, Iterable]) -> dict[str, str]:
    keysym_to_modifier: dict[str, str] = {}
    for modifier, keysyms in modifiers.items():
        for keysym in keysyms:
            existing_mod = keysym_to_modifier.get(keysym)
            if existing_mod and existing_mod != modifier:
                log.error("ERROR: keysym %s is mapped to both %s and %s !", keysym, modifier, existing_mod)
            else:
                keysym_to_modifier[keysym] = modifier
                if keysym in DEBUG_KEYSYMS:
                    log.info("set_all_keycodes() keysym_to_modifier[%s]=%s", keysym, modifier)
    log("keysym_to_modifier=%s", keysym_to_modifier)
    return keysym_to_modifier


def estr(entries) -> str:
    try:
        return csv(tuple(set(x[0] for x in entries)))
    except Exception:
        return csv(tuple(entries))


def set_all_keycodes(xkbmap_x11_keycodes, xkbmap_keycodes, preserve_server_keycodes, modifiers: dict[str, Iterable]):
    """
        Clients that have access to raw x11 keycodes should provide
        a `xkbmap_x11_keycodes` map, we otherwise fall back to using
        the `xkbmap_keycodes` gtk keycode list.
        We try to preserve the initial keycodes if asked to do so,
        we retrieve them from the current server keymap and combine
        them with the given keycodes.
        The `modifiers` dict can be obtained by calling
        `get_modifiers_from_meanings` or `get_modifiers_from_keycodes`.
        We use it to ensure that two modifiers are not
        mapped to the same keycode (which is not allowed).
        We return a translation map for keycodes after setting them up,
        the key is (keycode, keysym) and the value is the server keycode.
    """
    log("set_all_keycodes(%s.., %s.., %s.., %s)",
        str(xkbmap_x11_keycodes)[:60], str(xkbmap_keycodes)[:60], str(preserve_server_keycodes)[:60], modifiers)
    X11Keyboard = X11KeyboardBindings()

    # so we can validate entries:
    keysym_to_modifier = get_keysym_to_modifier_map(modifiers)

    def modifiers_for(entries) -> set[str]:
        """ entries can only point to a single modifier - verify """
        modifiers: set[str] = set()
        log_fn = log.debug
        for keysym, _ in entries:
            modifier = keysym_to_modifier.get(keysym)
            if modifier:
                modifiers.add(modifier)
            if keysym in DEBUG_KEYSYMS:
                log_fn = log.info
                break
        log_fn("modifiers_for(%s)=%s", entries, modifiers)
        return modifiers

    def filter_mappings(mappings, drop_extra_keys=False) -> dict[int, set]:
        filtered = {}
        invalid_keysyms = set()
        for keycode, entries in mappings.items():
            mods = modifiers_for(entries)
            if len(mods) > 1:
                log.warn("Warning: keymapping changed:")
                log.warn(" keycode %s points to %i modifiers: %s", keycode, len(mods), csv(tuple(mods)))
                log.warn(" from definition: %s", estr(entries))
                for mod in mods:
                    emod = [entry for entry in entries if mod in modifiers_for([entry])]
                    log.warn(" %s: %s", mod, estr(emod))
                # keep just the first one:
                mods = tuple(mods)[:1]
                mod = mods[0]
                entries = [entry for entry in entries if mod in modifiers_for([entry])]
                log.warn(" keeping: %s for %s", estr(entries), mod)
            # now remove entries for keysyms we don't have:
            f_entries = set((keysym, index) for keysym, index in entries
                            if keysym and X11Keyboard.parse_keysym(keysym) is not None)
            for keysym, _ in entries:
                if keysym and X11Keyboard.parse_keysym(keysym) is None:
                    invalid_keysyms.add(keysym)
            if not f_entries:
                log("keymapping removed invalid keycode entry %s pointing to only unknown keysyms: %s",
                    keycode, entries)
                continue
            if drop_extra_keys and not any(keysym for keysym, index in entries if (
                X11Keyboard.parse_keysym(keysym) is not None and keysym not in OPTIONAL_KEYS)
            ):
                log("keymapping removed keycode entry %s pointing to optional keys: %s", keycode, entries)
                continue
            filtered[keycode] = f_entries
        if invalid_keysyms:
            log.warn("Warning: the following keysyms are invalid and have not been mapped")
            log.warn(" %s", csv(invalid_keysyms))
        return filtered

    # get the list of keycodes (either from x11 keycodes or gtk keycodes):
    if xkbmap_x11_keycodes:
        log("using x11 keycodes: %s", xkbmap_x11_keycodes)
        dump_dict(xkbmap_x11_keycodes)
        keycodes = indexed_mappings(xkbmap_x11_keycodes)
    else:
        log("using gtk keycodes: %s", xkbmap_keycodes)
        keycodes = gtk_keycodes_to_mappings(xkbmap_keycodes)
    # filter to ensure only valid entries remain:
    log("keycodes=%s", keycodes)
    keycodes = filter_mappings(keycodes)

    # now lookup the current keycodes (if we need to preserve them)
    preserve_keycode_entries: dict[int, list[str]] = {}
    if preserve_server_keycodes:
        preserve_keycode_entries = X11Keyboard.get_keycode_mappings()
        log("preserved mappings:")
        dump_dict(preserve_keycode_entries)

    kcmin, kcmax = X11Keyboard.get_minmax_keycodes()
    for try_harder in (False, True):
        filtered_preserve_keycode_entries = filter_mappings(indexed_mappings(preserve_keycode_entries), try_harder)
        log("filtered_preserve_keycode_entries=%s", filtered_preserve_keycode_entries)
        trans, new_keycodes, missing_keycodes = translate_keycodes(kcmin, kcmax,
                                                                   keycodes, filtered_preserve_keycode_entries,
                                                                   keysym_to_modifier,
                                                                   try_harder)
        if not missing_keycodes:
            break
    instructions = keymap_to_xmodmap(new_keycodes)
    unset = apply_xmodmap(instructions)
    log("unset=%s", unset)
    return trans


def dump_dict(d: dict) -> None:
    for k, v in d.items():
        log("%s\t\t=\t%s", k, v)


def indexed_mappings(raw_mappings: dict[int, Iterable]) -> dict[int, set]:
    indexed: dict[int, set] = {}
    for keycode, keysyms in raw_mappings.items():
        pairs = set()
        log_fn = log.debug
        for i, keysym in enumerate(keysyms):
            if keysym in DEBUG_KEYSYMS:
                log_fn = log.info
            pairs.add((keysym, i))
        indexed[keycode] = pairs
        log_fn("indexed_mappings: %s=%s", keycode, pairs)
    return indexed


def gtk_keycodes_to_mappings(gtk_mappings: Iterable[tuple[Any, str, int, int, int]]
                             ) -> dict[int, set[tuple[str, int]]]:
    """
        Takes gtk keycodes as obtained by get_gtk_keymap, in the form:
        #[(keyval, keyname, keycode, group, level), ..]
        And returns a list of entries in the form:
        [[keysym, keycode, index], ..]
    """
    # use the keycodes supplied by gtk:
    mappings: dict[int, set[tuple[str, int]]] = {}
    for _, name, keycode, group, level in gtk_mappings:
        if keycode < 0:
            continue            # ignore old 'add_if_missing' client side code
        index = group*2+level
        mappings.setdefault(keycode, set()).add((name, index))
    return mappings


def x11_keycodes_to_list(x11_mappings: dict[int, Iterable]) -> list[tuple[str, int, int]]:
    """
        Takes x11 keycodes as obtained by get_keycode_mappings(), in the form:
        #{keycode : [keysyms], ..}
        And returns a list of entries in the form:
        [[keysym, keycode, index], ..]
    """
    entries = []
    if x11_mappings:
        for keycode, keysyms in x11_mappings.items():
            index = 0
            for keysym in keysyms:
                if keysym:
                    entries.append((keysym, int(keycode), index))
                    if keysym in DEBUG_KEYSYMS:
                        log.info("x11_keycodes_to_list: (%s, %s) : %s", keycode, keysyms, (keysym, int(keycode), index))
                index += 1
    return entries


def translate_keycodes(kcmin: int, kcmax: int, keycodes: dict[int, set],
                       preserve_keycode_entries: dict[int, set], keysym_to_modifier: dict[str, str],
                       try_harder=False) -> tuple[dict, dict, Sequence]:
    """
        The keycodes given may not match the range that the server supports,
        or some of those keycodes may not be usable (only one modifier can
        be mapped to a single keycode) or we want to preserve a keycode,
        or modifiers want to use the same keycode (which is not possible),
        so we return a translation map for those keycodes that have been
        remapped.
        The preserve_keycodes is a dict containing {keycode:[entries]}
        for keys we want to preserve the keycode for.
        Note: a client_keycode of '0' is valid (osx uses that),
        but server_keycode generally starts at 8...
    """
    log("translate_keycodes(%s, %s, %s, %s, %s, %s)",
        kcmin, kcmax, keycodes, preserve_keycode_entries, keysym_to_modifier, try_harder)
    # list of free keycodes we can use:
    free_keycodes: list[int] = [i for i in range(kcmin, kcmax+1) if i not in preserve_keycode_entries]
    keycode_trans: dict[str | tuple[int, str], int] = {}              # translation map from client keycode to our server keycode
    server_keycodes: dict[int, Any] = {}            # the new keycode definitions
    missing_keycodes = []           # the groups of entries we failed to map due to lack of free keycodes

    # to do faster lookups:
    preserve_keysyms_map = {}
    for keycode, entries in preserve_keycode_entries.items():
        for keysym, _ in entries:
            preserve_keysyms_map.setdefault(keysym, set()).add(keycode)
    for k in DEBUG_KEYSYMS:
        log.info("preserve_keysyms_map[%s]=%s", k, preserve_keysyms_map.get(k))

    def do_assign(keycode: int, server_keycode: int, entries, override_server_keycode=False) -> int:
        """ may change the keycode if needed
            in which case we update the entries and populate 'keycode_trans'
        """
        log_fn = log.debug
        for name, _ in entries:
            if name in DEBUG_KEYSYMS:
                log_fn = log.info
                break
        if (server_keycode in server_keycodes) and not override_server_keycode:
            log_fn("assign: server keycode %s already in use: %s", server_keycode, server_keycodes.get(server_keycode))
            server_keycode = -1
        elif server_keycode > 0 and (server_keycode < kcmin or server_keycode > kcmax):
            log_fn("assign: keycode %s out of range (%s to %s)", server_keycode, kcmin, kcmax)
            server_keycode = -1
        if server_keycode <= 0:
            if free_keycodes:
                server_keycode = free_keycodes[0]
                log_fn("set_keycodes key %s using free keycode=%s", entries, server_keycode)
            else:
                msg = "set_keycodes: no free keycodes!, cannot translate %s: %s", server_keycode, tuple(entries)
                if try_harder:
                    log.error(*msg)
                else:
                    log_fn(*msg)
                missing_keycodes.append(entries)
                server_keycode = -1
        if server_keycode > 0:
            log_fn("set_keycodes key %s (%s) mapped to keycode=%s", keycode, tuple(entries), server_keycode)
            # can't use it anymore!
            if server_keycode in free_keycodes:
                free_keycodes.remove(server_keycode)
            # record it in trans map:
            for name, _ in entries:
                # noinspection PyChainedComparisons
                if keycode >= 0 and server_keycode != keycode:
                    keycode_trans[(keycode, name)] = server_keycode
                    log_fn(f"keycode_trans[({keycode}, {name})]={server_keycode}")
                keycode_trans[name] = server_keycode
                log_fn(f"keycode_trans[{name}]={server_keycode}")
            server_keycodes[server_keycode] = entries
        return server_keycode

    def assign(client_keycode: int, entries) -> int:
        if not entries:
            return 0
        # all the keysyms for this keycode:
        keysyms = {keysym for keysym, _ in entries}
        if not keysyms:
            return 0
        if len(keysyms) == 1 and tuple(keysyms)[0] == '0xffffff':
            log("skipped invalid keysym: %s / %s", client_keycode, entries)
            return 0
        log_fn = log.debug
        if any(bool(k) for k in keysyms if k in DEBUG_KEYSYMS):
            log_fn = log.info
        log_fn("assign(%s, %s)", client_keycode, entries)

        if not preserve_keycode_entries:
            return do_assign(client_keycode, client_keycode, entries)
        if len(keysyms) == 1:
            # only one keysym, replace with single entry
            # noinspection PySetFunctionToLiteral
            entries = set([(tuple(keysyms)[0], 0)])

        # the candidate preserve entries: those that have at least one of the keysyms:
        preserve_keycode_matches = {}
        for keysym in tuple(keysyms):
            keycodes = preserve_keysyms_map.get(keysym, [])
            for keycode in keycodes:
                v = preserve_keycode_entries.get(keycode)
                preserve_keycode_matches[keycode] = v
                log_fn("preserve_keycode_matches[%s]=%s", keycode, v)

        if not preserve_keycode_matches:
            log_fn("no preserve matches for %s", tuple(entries))
            return do_assign(client_keycode, -1, entries)         # nothing to preserve

        log_fn("preserve matches for %s : %s", entries, preserve_keycode_matches)
        # direct superset:
        for p_keycode, p_entries in preserve_keycode_matches.items():
            if entries.issubset(p_entries):
                log_fn("found direct preserve superset for client keycode %s %s -> server keycode %s %s",
                       client_keycode, tuple(entries), p_keycode, tuple(p_entries))
                return do_assign(client_keycode, p_keycode, p_entries, override_server_keycode=True)
            if p_entries.issubset(entries):
                log_fn("found direct superset of preserve for client keycode %s %s -> server keycode %s %s",
                       client_keycode, tuple(entries), p_keycode, tuple(p_entries))
                return do_assign(client_keycode, p_keycode, entries, override_server_keycode=True)

        # ignoring indexes, but requiring at least as many keysyms:
        for p_keycode, p_entries in preserve_keycode_matches.items():
            p_keysyms = set(keysym for keysym, _ in p_entries)
            if keysyms.issubset(p_keysyms) and len(p_entries) > len(entries):
                log_fn("found keysym preserve superset with more keys for %s : %s",
                       tuple(entries), tuple(p_entries))
                return do_assign(client_keycode, p_keycode, p_entries, override_server_keycode=True)
            if p_keysyms.issubset(keysyms):
                log_fn("found keysym superset of preserve with more keys for %s : %s",
                       tuple(entries), tuple(p_entries))
                return do_assign(client_keycode, p_keycode, entries, override_server_keycode=True)

        if try_harder:
            # try to match the main key only:
            main_key = set((keysym, index) for keysym, index in entries if index == 0)
            if len(main_key) == 1:
                for p_keycode, p_entries in preserve_keycode_matches.items():
                    if main_key.issubset(p_entries):
                        log_fn("found main key superset for %s : %s", main_key, tuple(p_entries))
                        return do_assign(client_keycode, p_keycode, p_entries, override_server_keycode=True)

        log_fn("no matches for %s", tuple(entries))
        return do_assign(client_keycode, -1, entries)

    # now try to assign each keycode:
    for keycode in sorted(keycodes.keys()):
        entries = keycodes.get(keycode)
        log("assign(%s, %s)", keycode, entries)
        assign(keycode, entries)

    # add all the other preserved ones that have not been mapped to any client keycode:
    for server_keycode, entries in preserve_keycode_entries.items():
        if server_keycode not in server_keycodes:
            do_assign(-1, server_keycode, entries)

    # find all keysyms assigned so far:
    all_keysyms = set()
    for entries in server_keycodes.values():
        for x in [keysym for keysym, _ in entries]:
            all_keysyms.add(x)
    log("all_keysyms=%s", all_keysyms)

    # defined keysyms for modifiers if some are missing:
    for keysym, modifier in keysym_to_modifier.items():
        if keysym not in all_keysyms:
            log_fn = log.debug
            if keysym in DEBUG_KEYSYMS:
                log_fn = log.info
            log_fn("found missing keysym %s for modifier %s, will add it", keysym, modifier)
            # noinspection PySetFunctionToLiteral
            new_keycode = set([(keysym, 0)])
            server_keycode = assign(-1, new_keycode)
            log_fn("assigned keycode %s for key '%s' of modifier '%s'", server_keycode, keysym, modifier)

    log("translated keycodes=%s", keycode_trans)
    log("%s free keycodes=%s", len(free_keycodes), free_keycodes)
    return keycode_trans, server_keycodes, missing_keycodes


def keymap_to_xmodmap(trans_keycodes: dict[int, Any]) -> list[tuple]:
    """
        Given a dict with keycodes as keys and lists of keyboard entries as values,
        (keysym, keycode, index)
        produce a list of xmodmap instructions to set the x11 keyboard to match it,
        in the form:
        ("keycode", keycode, [keysyms])
    """
    missing_keysyms = []            # the keysyms lookups which failed
    instructions = []
    all_entries = []
    for entries in trans_keycodes.values():
        all_entries += entries
    keysyms_per_keycode = max([index for _, index in all_entries])+1
    for server_keycode, entries in trans_keycodes.items():
        keysyms = [None]*keysyms_per_keycode
        names = [""]*keysyms_per_keycode
        sentries = sorted(entries, key=lambda x: x[1])
        for name, index in sentries:
            assert 0 <= index < keysyms_per_keycode
            try:
                X11Keyboard = X11KeyboardBindings()
                keysym = X11Keyboard.parse_keysym(name)
            except Exception:
                keysym = None
            if keysym is None:
                if name != "":
                    missing_keysyms.append(name)
            else:
                if keysyms[index] is not None:
                    # if the client provides multiple keysyms for the same index,
                    # replace with the new one if the old one exists elsewhere,
                    # or skip it if we have another entry for it
                    can_override = any(True for i, v in enumerate(keysyms) if i < index and v == keysyms[index])
                    can_skip = any(True for i, v in enumerate(keysyms) if i != index and v == keysym)
                    log_fn = log.debug if can_override or can_skip else log.warn
                    log_fn("Warning: more than one keysym for keycode %-3i at index %i:", server_keycode, index)
                    log_fn(" entries=%s", csv(tuple(sentries)))
                    log_fn(" keysyms=%s", csv(keysyms))
                    log_fn(" assigned keysym=%s", names[index])
                    log_fn(" wanted keysym=%s", name)
                    if can_override:
                        log_fn(" current value also found at another index, overriding it")
                    elif can_skip:
                        log_fn(" new value also found elsewhere, skipping it")
                    else:
                        continue
                names[index] = name
                keysyms[index] = keysym
                if name in DEBUG_KEYSYMS:
                    log.info("keymap_to_xmodmap: keysyms[%s]=%s (%s)", index, keysym, name)
        # remove empty keysyms:
        while keysyms and keysyms[0] is None:
            keysyms = keysyms[1:]
        log_fn = log.debug
        if any(bool(k) for k in keysyms if k in DEBUG_KEYSYMS):
            log_fn = log.info
        log_fn("%s: %s -> %s", server_keycode, names, keysyms)
        instructions.append(("keycode", server_keycode, keysyms))

    if missing_keysyms:
        log.error("cannot find the X11 keysym for the following key names: %s", set(missing_keysyms))
    log("instructions=%s", instructions)
    return instructions


################################################################################
# modifiers

def clear_modifiers() -> None:
    instructions = [("clear", i) for i in range(0, 8)]
    apply_xmodmap(instructions)


def set_modifiers(modifiers: dict[str, Iterable[str]]) -> None:
    """
        modifiers is a dict: {modifier : [keynames]}
        Note: the same keysym cannot appear in more than one modifier
    """
    X11Keyboard = X11KeyboardBindings()
    instructions: list[tuple[str, str, Iterable[str]]] = []
    for modifier, keynames in modifiers.items():
        mod = X11Keyboard.parse_modifier(modifier)
        if mod >= 0:
            instructions.append(("add", mod, keynames))
        else:
            log.error("Error: unknown modifier %s", modifier)
    log("set_modifiers: %s", instructions)

    def apply_or_trim(instructions: list[tuple[str, str, Iterable[str]]]) -> None:
        err = apply_xmodmap(instructions)
        log("set_modifiers: err=%s", err)
        if not err:
            return
        log("set_modifiers %s failed, retrying one more at a time", instructions)
        count = len(instructions)
        for i in range(1, count):
            subset = instructions[:i]
            log("set_modifiers testing with [:%s]=%s", i, subset)
            err = apply_xmodmap(subset)
            log("err=%s", err)
            if err:
                log.warn("Warning: removing problematic modifier mapping: %s", csv(instructions[i-1]))
                instructions = instructions[:i-1]+instructions[i:]
                apply_or_trim(instructions)
                return
    apply_or_trim(instructions)


def get_modifiers_from_meanings(xkbmap_mod_meanings: dict[str, str]) -> dict[str, list[str]]:
    """
        xkbmap_mod_meanings maps a keyname to a modifier
        returns keynames_for_mod: {modifier : [keynames]}
    """
    # first generate a {modifier : [keynames]} dict:
    modifiers = {}
    for keyname, modifier in xkbmap_mod_meanings.items():
        keynames = modifiers.setdefault(modifier, [])
        if keyname not in keynames:
            keynames.append(keyname)
    log("get_modifiers_from_meanings(%s) modifier dict=%s", xkbmap_mod_meanings, modifiers)
    return modifiers


def get_modifiers_from_keycodes(xkbmap_keycodes: Iterable, add_default_modifiers=True) -> dict[str, list[str]]:
    """
        Some platforms can't tell us about modifier mappings
        So we try to find matches from the defaults below:
    """
    pref = DEFAULT_MODIFIER_MEANINGS
    # keycodes are: {keycode : (keyval, name, keycode, group, level)}
    matches = {}
    log("get_modifiers_from_keycodes(%s...)", str(xkbmap_keycodes)[:160])
    all_keynames = set()
    for entry in xkbmap_keycodes:
        _, keyname, _, _, _ = entry
        modifier = pref.get(keyname)
        if modifier:
            keynames = matches.setdefault(modifier, [])
            if keyname not in keynames:
                keynames.append(keyname)
            all_keynames.add(keyname)
    if add_default_modifiers:
        # try to add missing ones (magic!)
        defaults = {}
        for keyname, modifier in DEFAULT_MODIFIER_MEANINGS.items():
            if keyname in all_keynames:
                continue            # already defined
            if modifier not in matches:
                # define it since it is completely missing
                keynames = defaults.setdefault(modifier, [])
                if keyname not in keynames:
                    keynames.append(keyname)
            elif modifier in ["shift", "lock", "control", "mod1", "mod2"] or keyname == "ISO_Level3_Shift":
                # these are always added,
                # even if a record for the modifier already exists
                keynames = matches.setdefault(modifier, [])
                if keyname not in keynames:
                    keynames.append(keyname)
        log("get_modifiers_from_keycodes(...) adding defaults: %s", defaults)
        matches.update(defaults)
    log("get_modifiers_from_keycodes(...)=%s", matches)
    return matches


def map_missing_modifiers(keynames_for_mod: dict[str, Iterable]):
    X11Keyboard = X11KeyboardBindings()
    x11_keycodes = X11Keyboard.get_keycode_mappings()
    min_keycode, max_keycode = X11Keyboard.get_minmax_keycodes()
    free_keycodes = [x for x in range(min_keycode, max_keycode) if x not in x11_keycodes]
    log("map_missing_modifiers(%s) min_keycode=%i max_keycode=%i, free_keycodes=%s",
        keynames_for_mod, min_keycode, max_keycode, free_keycodes)
    keysyms_to_keycode = {}
    for keycode, keysyms in x11_keycodes.items():
        for keysym in keysyms:
            keysyms_to_keycode.setdefault(keysym, []).append(keycode)
    xmodmap_changes = []
    for mod, keysyms in keynames_for_mod.items():
        missing = []
        keysym = ""
        for keysym in keysyms:
            if keysym not in keysyms_to_keycode:
                missing.append(keysym)
        if missing:
            log("map_missing_modifiers: no keycode found for modifier keys %s (%s)", csv(missing), mod)
            if not free_keycodes:
                log.warn("Warning: keymap is full, cannot add '%s' for modifier '%s'", keysym, mod)
            else:
                keycode = free_keycodes.pop()
                xmodmap_changes.append(("keycode", keycode, missing))
    if xmodmap_changes:
        log("xmodmap_changes=%s", xmodmap_changes)
        X11Keyboard.set_xmodmap(xmodmap_changes)


def grok_modifier_map(meanings: dict) -> dict[str, int]:
    """
    Return a dict mapping modifier names to corresponding X modifier bitmasks.
    """
    # is this still correct for GTK3?
    modifier_map = MODIFIER_MAP.copy()
    modifier_map |= {
        "scroll": 0,
        "num": 0,
        "meta": 0,
        "super": 0,
        "hyper": 0,
        "alt": 0,
    }
    if not meanings:
        meanings = DEFAULT_MODIFIER_MEANINGS

    from xpra.x11.xkbhelper import get_keycode_mappings
    with xsync:
        mappings = get_keycode_mappings()
        X11Keyboard = X11KeyboardBindings()
        max_keypermod, keycodes = X11Keyboard.get_modifier_map()
    assert len(keycodes) == 8 * max_keypermod
    for i in range(8):
        for j in range(max_keypermod):
            keycode = keycodes[i * max_keypermod + j]
            if keycode:
                keysyms = mappings.get(keycode, ())
                for keysym in keysyms:
                    modifier = meanings.get(keysym, "")
                    if modifier:
                        modifier_map[modifier] |= (1 << i)
    return modifier_map
