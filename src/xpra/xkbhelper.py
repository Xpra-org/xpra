# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import subprocess

from wimpiggy.error import trap
from wimpiggy.lowlevel import (set_xmodmap,                 #@UnresolvedImport
                              parse_keysym,                 #@UnresolvedImport
                              parse_modifier,               #@UnresolvedImport
                              get_minmax_keycodes,          #@UnresolvedImport
                              ungrab_all_keys,              #@UnresolvedImport
                              unpress_all_keys,             #@UnresolvedImport
                              get_keycode_mappings)         #@UnresolvedImport
from wimpiggy.log import Logger
log = Logger()

debug = log.info
debug = log.debug
verbose = log.debug


def signal_safe_exec(cmd, stdin):
    """ this is a bit of a hack,
    the problem is that we won't catch SIGCHLD at all while this command is running! """
    import signal
    try:
        oldsignal = signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (out,err) = process.communicate(stdin)
        code = process.poll()
        l=log.debug
        if code!=0:
            l=log.error
        l("signal_safe_exec(%s,%s) stdout='%s'", cmd, stdin, out)
        l("signal_safe_exec(%s,%s) stderr='%s'", cmd, stdin, err)
        return  code
    finally:
        signal.signal(signal.SIGCHLD, oldsignal)

def exec_keymap_command(args, stdin=None):
    try:
        returncode = signal_safe_exec(args, stdin)
        def logstdin():
            if not stdin or len(stdin)<32:
                return  stdin
            return stdin[:30].replace("\n", "\\n")+".."
        if returncode==0:
            if not stdin:
                log("%s", args)
            else:
                log("%s with stdin=%s", args, logstdin())
        else:
            log.error("%s with stdin=%s, failed with exit code %s", args, logstdin(), returncode)
        return returncode
    except Exception, e:
        log.error("error calling '%s': %s" % (str(args), e))
        return -1


def clean_keyboard_state():
    import gtk.gdk
    try:
        ungrab_all_keys(gtk.gdk.get_default_root_window())
    except:
        log.error("error ungrabbing keys", exc_info=True)
    try:
        unpress_all_keys(gtk.gdk.get_default_root_window())
    except:
        log.error("error unpressing keys", exc_info=True)

################################################################################
# keyboard layouts

def do_set_keymap(xkbmap_layout, xkbmap_variant,
                  xkbmap_print, xkbmap_query):
    """ xkbmap_layout is the generic layout name (used on non posix platforms)
        xkbmap_variant is the layout variant (may not be set)
        xkbmap_print is the output of "setxkbmap -print" on the client
        xkbmap_query is the output of "setxkbmap -query" on the client
        Use those to try to setup the correct keyboard map for the client
        so that all the keycodes sent will be mapped
    """
    #First we try to use data from setxkbmap -query
    if xkbmap_query:
        log.debug("do_set_keymap using xkbmap_query")
        """ The xkbmap_query data will look something like this:
        rules:      evdev
        model:      evdev
        layout:     gb
        options:    grp:shift_caps_toggle
        And we want to call something like:
        setxkbmap -rules evdev -model evdev -layout gb
        setxkbmap -option "" -option grp:shift_caps_toggle
        (we execute the options separately in case that fails..)
        """
        #parse the data into a dict:
        settings = {}
        opt_re = re.compile("(\w*):\s*(.*)")
        for line in xkbmap_query.splitlines():
            m = opt_re.match(line)
            if m:
                settings[m.group(1)] = m.group(2).strip()
        #construct the command line arguments for setxkbmap:
        args = ["setxkbmap"]
        used_settings = {}
        for setting in ["rules", "model", "layout"]:
            if setting in settings:
                value = settings.get(setting)
                args += ["-%s" % setting, value]
                used_settings[setting] = value
        if len(args)==1:
            log.warn("do_set_keymap could not find rules, model or layout in the xkbmap query string..")
        log.info("setting keymap: %s", used_settings)
        exec_keymap_command(args)
        #try to set the options:
        if "options" in settings:
            log.info("setting keymap options: %s", settings.get("options"))
            exec_keymap_command(["setxkbmap", "-option", "", "-option", settings.get("options")])
    elif xkbmap_print:
        debug("do_set_keymap using xkbmap_print")
        #try to guess the layout by parsing "setxkbmap -print"
        try:
            sym_re = re.compile("\s*xkb_symbols\s*{\s*include\s*\"([\w\+]*)")
            for line in xkbmap_print.splitlines():
                m = sym_re.match(line)
                if m:
                    layout = m.group(1)
                    log.info("guessing keyboard layout='%s'" % layout)
                    exec_keymap_command(["setxkbmap", layout])
                    break
        except Exception, e:
            log.info("error setting keymap: %s" % e)
    else:
        layout = xkbmap_layout or "us"
        log.info("setting keyboard layout to '%s'", layout)
        set_layout = ["setxkbmap", "-layout", layout]
        if xkbmap_variant:
            set_layout += ["-variant", xkbmap_variant]
        if not exec_keymap_command(set_layout) and xkbmap_variant:
            log.info("error setting keymap with variant %s, retrying with just layout %s", xkbmap_variant, layout)
            set_layout = ["setxkbmap", "-layout", layout]
            exec_keymap_command(set_layout)

    display = os.environ.get("DISPLAY")
    if xkbmap_print:
        #there may be a junk header, if so remove it:
        pos = xkbmap_print.find("xkb_keymap {")
        if pos>0:
            xkbmap_print = xkbmap_print[pos:]
        log.info("setting full keymap definition from client via xkbcomp")
        exec_keymap_command(["xkbcomp", "-", display], xkbmap_print)


################################################################################
# keycodes

def apply_xmodmap(instructions):
    import gtk.gdk
    try:
        unset = trap.call_synced(set_xmodmap, gtk.gdk.get_default_root_window(), instructions)
    except:
        log.error("apply_xmodmap", exc_info=True)
        unset = instructions
    if unset is None:
        #None means an X11 error occurred, re-do all:
        unset = instructions
    return unset

def set_all_keycodes(xkbmap_x11_keycodes, xkbmap_keycodes, preserve_server_keycodes, modifiers):
    """
        Clients that have access to raw x11 keycodes should provide
        an xkbmap_x11_keycodes map, we otherwise fallback to using
        the xkbmap_keycodes gtk keycode list.
        We try to preserve the initial keycodes if asked to do so,
        we retrieve them from the current server keymap and combine
        them with the given keycodes.
        The modifiers dict can be obtained by calling
        get_modifiers_from_meanings or get_modifiers_from_keycodes.
        We use it to ensure that two modifiers are not
        mapped to the same keycode (which is not allowed).
        We return a translation map for keycodes after setting them up,
        the key is (keycode, keysym) and the value is the server keycode.
    """
    debug("set_all_keycodes(%s.., %s.., %s.., %s)", str(xkbmap_x11_keycodes)[:60], str(xkbmap_keycodes)[:60], str(preserve_server_keycodes)[:60], modifiers)

    #so we can validate entries:
    keysym_to_modifier = {}
    for modifier, keysyms in modifiers.items():
        for keysym in keysyms:
            existing_mod = keysym_to_modifier.get(keysym)
            if existing_mod and existing_mod!=modifier:
                log.error("ERROR: keysym %s is mapped to both %s and %s !", keysym, modifier, existing_mod)
            else:
                keysym_to_modifier[keysym] = modifier
    debug("keysym_to_modifier=%s", keysym_to_modifier)

    def modifiers_for(entries):
        """ entries can only point to a single modifier - verify """
        modifiers = set()
        for keysym, _ in entries:
            modifier = keysym_to_modifier.get(keysym)
            if modifier:
                modifiers.add(modifier)
        return modifiers

    def filter_mappings(mappings):
        filtered = {}
        for keycode, entries in mappings.items():
            mods = modifiers_for(entries)
            if len(mods)<=1:
                filtered[keycode] = entries
            else:
                log.warn("keymapping removed invalid keycode entry %s pointing to more than one modifier (%s): %s", keycode, mods, entries)
        return filtered

    #get the list of keycodes (either from x11 keycodes or gtk keycodes):
    if xkbmap_x11_keycodes and len(xkbmap_x11_keycodes)>0:
        debug("using x11 keycodes: %s", xkbmap_x11_keycodes)
        dump_dict(xkbmap_x11_keycodes)
        keycodes = indexed_mappings(xkbmap_x11_keycodes)
    else:
        debug("using gtk keycodes: %s", xkbmap_keycodes)
        keycodes = gtk_keycodes_to_mappings(xkbmap_keycodes)
    #filter to ensure only valid entries remain:
    debug("keycodes=%s", keycodes)
    keycodes = filter_mappings(keycodes)

    #now lookup the current keycodes (if we need to preserve them)
    preserve_keycode_entries = {}
    if preserve_server_keycodes:
        import gtk.gdk
        preserve_keycode_entries = get_keycode_mappings(gtk.gdk.get_default_root_window())
        debug("preserved mappings:")
        dump_dict(preserve_keycode_entries)
        debug("preserve_keycode_entries=%s", preserve_keycode_entries)
        preserve_keycode_entries = filter_mappings(indexed_mappings(preserve_keycode_entries))

    kcmin, kcmax = get_minmax_keycodes()
    trans, new_keycodes = translate_keycodes(kcmin, kcmax, keycodes, preserve_keycode_entries, keysym_to_modifier)
    instructions = keymap_to_xmodmap(new_keycodes)
    unset = apply_xmodmap(instructions)
    debug("unset=%s", unset)
    return trans

def dump_dict(d):
    for k,v in d.items():
        debug("%s\t\t=\t%s", k, v)

def group_by_keycode(entries):
    keycodes = {}
    for keysym, keycode, index in entries:
        keycodes.setdefault(keycode, set()).add((keysym, index))
    return keycodes

def indexed_mappings(raw_mappings):
    indexed = {}
    for keycode, keysyms in raw_mappings.items():
        pairs = set()
        for i in range(0, len(keysyms)):
            pairs.add((keysyms[i], i))
        indexed[keycode] = pairs
    return indexed


def gtk_keycodes_to_mappings(gtk_mappings):
    """
        Takes gtk keycodes as obtained by get_gtk_keymap, in the form:
        #[(keyval, keyname, keycode, group, level), ..]
        And returns a list of entries in the form:
        [[keysym, keycode, index], ..]
    """
    #use the keycodes supplied by gtk:
    mappings = {}
    for _, name, keycode, group, level in gtk_mappings:
        if keycode<=0:
            continue            #ignore old 'add_if_missing' client side code
        index = group*2+level
        mappings.setdefault(keycode, set()).add((name, index))
    return mappings

def x11_keycodes_to_list(x11_mappings):
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
                    entries.append([keysym, int(keycode), index])
                index += 1
    return entries


def translate_keycodes(kcmin, kcmax, keycodes, preserve_keycode_entries={}, keysym_to_modifier={}):
    """
        The keycodes given may not match the range that the server supports,
        or some of those keycodes may not be usable (only one modifier can
        be mapped to a single keycode) or we want to preserve a keycode,
        or modifiers want to use the same keycode (which is not possible),
        so we return a translation map for those keycodes that have been
        remapped.
        The preserve_keycodes is a dict containing {keycode:[entries]}
        for keys we want to preserve the keycode for.
    """
    debug("translate_keycodes(%s, %s, %s, %s, %s)", kcmin, kcmax, keycodes, preserve_keycode_entries, keysym_to_modifier)
    #list of free keycodes we can use:
    free_keycodes = [i for i in range(kcmin, kcmax) if i not in preserve_keycode_entries]
    keycode_trans = {}              #translation map from client keycode to our server keycode
    server_keycodes = {}            #the new keycode definitions

    #to do faster lookups:
    preserve_keysyms_map = {}
    for keycode, entries in preserve_keycode_entries.items():
        for keysym, _ in entries:
            preserve_keysyms_map.setdefault(keysym, set()).add(keycode)

    def do_assign(keycode, server_keycode, entries):
        """ may change the keycode if needed
            in which case we update the entries and populate 'keycode_trans'
        """
        if server_keycode in server_keycodes:
            debug("assign: keycode %s already in use: %s", server_keycode, server_keycodes.get(server_keycode))
            server_keycode = 0
        elif server_keycode>0 and (server_keycode<kcmin or server_keycode>kcmax):
            debug("assign: keycode %s out of range (%s to %s)", server_keycode, kcmin, kcmax)
            server_keycode = 0
        if server_keycode<=0:
            if len(free_keycodes)>0:
                server_keycode = free_keycodes[0]
                debug("set_keycodes key %s using free keycode=%s", entries, server_keycode)
            else:
                log.error("set_keycodes: no free keycodes!, cannot translate %s: %s", server_keycode, entries)
                server_keycode = 0
        if server_keycode>0:
            verbose("set_keycodes key %s (%s) mapped to keycode=%s", keycode, entries, server_keycode)
            #can't use it any more!
            if server_keycode in free_keycodes:
                free_keycodes.remove(server_keycode)
            #record it in trans map:
            for name, _ in entries:
                if keycode>0 and server_keycode!=keycode:
                    keycode_trans[(keycode, name)] = server_keycode
                keycode_trans[name] = server_keycode
            server_keycodes[server_keycode] = entries
        return server_keycode

    def assign(client_keycode, entries):
        if len(entries)==0:
            return 0
        if len(preserve_keycode_entries)==0:
            return do_assign(client_keycode, client_keycode, entries)
        #all the keysyms for this keycode:
        keysyms = set([keysym for keysym, _ in entries])
        if len(keysyms)==0:
            return 0
        if len(keysyms)==1:
            #only one keysym, replace with single entry
            entries = set([(list(keysyms)[0], 0)])

        #the candidate preserve entries: those that have at least one of the keysyms:
        preserve_keycode_matches = {}
        for keysym in list(keysyms):
            keycodes = preserve_keysyms_map.get(keysym, [])
            for keycode in keycodes:
                preserve_keycode_matches[keycode] = preserve_keycode_entries.get(keycode)

        if len(preserve_keycode_matches)==0:
            debug("no preserve matches for %s", entries)
            return do_assign(client_keycode, 0, entries)         #nothing to preserve

        debug("preserve matches for %s : %s", entries, preserve_keycode_matches)
        #direct superset:
        for p_keycode, p_entries in preserve_keycode_matches.items():
            if entries.issubset(p_entries):
                debug("found direct superset for %s : %s -> %s : %s", client_keycode, entries, p_keycode, p_entries)
                return do_assign(client_keycode, p_keycode, p_entries)

        #ignoring indexes, but requiring at least as many keysyms:
        for p_keycode, p_entries in preserve_keycode_matches.items():
            p_keysyms = [keysym for keysym,_ in p_entries]
            if keysyms.issubset(p_keysyms):
                if len(p_entries)>len(entries):
                    debug("found keysym superset with more keys for %s : %s", entries, p_entries)
                    return do_assign(client_keycode, p_keycode, p_entries)

        debug("no matches for %s", entries)
        return do_assign(client_keycode, 0, entries)

    #now try to assign each keycode:
    for keycode in sorted(keycodes.keys()):
        entries = keycodes.get(keycode)
        debug("assign(%s, %s)", keycode, entries)
        assign(keycode, entries)

    #add all the other preserved ones that have not been mapped to any client keycode:
    for server_keycode, entries in preserve_keycode_entries.items():
        if server_keycode not in server_keycodes:
            do_assign(0, server_keycode, entries)

    #find all keysyms assigned so far:
    all_keysyms = set()
    for entries in server_keycodes.values():
        for x in [keysym for keysym, _ in entries]:
            all_keysyms.add(x)
    debug("all_keysyms=%s", all_keysyms)

    #defined keysyms for modifiers if some are missing:
    for keysym, modifier in keysym_to_modifier.items():
        if keysym not in all_keysyms:
            debug("found missing keysym %s for modifier %s, will add it", keysym, modifier)
            new_keycode = set([(keysym, 0)])
            server_keycode = assign(0, new_keycode)
            debug("assigned keycode %s for key '%s' of modifier '%s'", server_keycode, keysym, modifier)

    debug("translated keycodes=%s", keycode_trans)
    debug("%s free keycodes=%s", len(free_keycodes), free_keycodes)
    return keycode_trans, server_keycodes


def keymap_to_xmodmap(trans_keycodes):
    """
        Given a dict with keycodes as keys and lists of keyboard entries as values,
        (keysym, keycode, index)
        produce a list of xmodmap instructions to set the x11 keyboard to match it,
        in the form:
        ("keycode", keycode, [keysyms])
    """
    missing_keysyms = []            #the keysyms lookups which failed
    instructions = []
    all_entries = []
    for entries in trans_keycodes.values():
        all_entries += entries
    keysyms_per_keycode = max([index for _, index in all_entries])+1
    for server_keycode, entries in trans_keycodes.items():
        keysyms = [None]*keysyms_per_keycode
        names = [""]*keysyms_per_keycode
        for name, index in entries:
            assert 0<=index and index<keysyms_per_keycode
            names[index] = name
            try:
                keysym = parse_keysym(name)
            except:
                keysym = None
            if keysym is None:
                if name!="":
                    missing_keysyms.append(name)
            else:
                if keysyms[index] is not None:
                    log.warn("we already have a keysym for %s at index %s: %s, entries=%s", server_keycode, index, keysyms[index], entries)
                else:
                    keysyms[index] = keysym
        #remove "duplicates":
        while len(keysyms)>=4 and keysyms[0]==keysyms[2] and keysyms[1]==keysyms[3]:
            keysyms = keysyms[2:]
        while len(keysyms)>=0 and keysyms[0] is None:
            keysyms = keysyms[1:]
        if len(set(keysyms))==1:
            keysyms = [keysyms[0]]
        debug("%s: %s -> %s", server_keycode, names, keysyms)
        instructions.append(("keycode", server_keycode, keysyms))

    if len(missing_keysyms)>0:
        log.error("cannot find the X11 keysym for the following key names: %s", set(missing_keysyms))
    debug("instructions=%s", instructions)
    return  instructions


################################################################################
# modifiers

def clear_modifiers(modifiers):
    instructions = []
    for i in range(0, 8):
        instructions.append(("clear", i))
    apply_xmodmap(instructions)

def set_modifiers(modifiers):
    """
        modifiers is a dict: {modifier : [keynames]}
        Note: the same keysym cannot appear in more than one modifier
    """
    instructions = []
    for modifier, keynames in modifiers.items():
        mod = parse_modifier(modifier)
        if mod>=0:
            instructions.append(("add", mod, keynames))
        else:
            log.error("set_modifiers_from_dict: unknown modifier %s", modifier)
    debug("set_modifiers: %s", instructions)
    unset = apply_xmodmap(instructions)
    debug("unset=%s", unset)
    if len(unset):
        log.info("set_modifiers %s failed, retrying one more at a time", instructions)
        l = len(instructions)
        for i in range(1, l):
            subset = instructions[:i]
            debug("set_modifiers testing with [:%s]=%s", i, subset)
            unset = apply_xmodmap(subset)
            debug("unset=%s", unset)
            if len(unset)>0:
                log.warn("the problematic modifier mapping is: %s", instructions[i-1])
                break
    return  modifiers


def get_modifiers_from_meanings(xkbmap_mod_meanings):
    """
        xkbmap_mod_meanings maps a keyname to a modifier
        returns keynames_for_mod: {modifier : [keynames]}
    """
    #first generate a {modifier : [keynames]} dict:
    modifiers = {}
    for keyname, modifier in xkbmap_mod_meanings.items():
        modifiers.setdefault(modifier, set()).add(keyname)
    debug("get_modifiers_from_meanings(%s) modifier dict=%s", xkbmap_mod_meanings, modifiers)
    return modifiers

def get_modifiers_from_keycodes(xkbmap_keycodes):
    """
        Some platforms can't tell us about modifier mappings
        So we try to find matches from the defaults below:
    """
    from xpra.keys import DEFAULT_MODIFIER_MEANINGS
    pref = DEFAULT_MODIFIER_MEANINGS
    #keycodes are: {keycode : (keyval, name, keycode, group, level)}
    matches = {}
    debug("get_modifiers_from_keycodes(%s...)", str(xkbmap_keycodes))
    debug("get_modifiers_from_keycodes(%s...)", str(xkbmap_keycodes)[:160])
    all_keynames = set()
    for entry in xkbmap_keycodes:
        _, keyname, _, _, _ = entry
        modifier = pref.get(keyname)
        if modifier:
            keynames = matches.setdefault(modifier, set())
            keynames.add(keyname)
            all_keynames.add(keyname)
    #try to add missings ones (magic!)
    defaults = {}
    for keyname, modifier in DEFAULT_MODIFIER_MEANINGS.items():
        if keyname in all_keynames:
            continue            #aleady defined
        if modifier not in matches:
            #define it since it is completely missing
            defaults.setdefault(modifier, set()).add(keyname)
        elif modifier in ["shift", "lock", "control", "mod1", "mod2"]:
            #these ones we always add them, even if a record for this modifier already exists
            matches.setdefault(modifier, set()).add(keyname)
    debug("get_modifiers_from_keycodes(...) adding defaults: %s", defaults)
    matches.update(defaults)
    debug("get_modifiers_from_keycodes(...)=%s", matches)
    return matches
