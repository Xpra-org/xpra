# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import subprocess

from wimpiggy.error import trap
from wimpiggy.lowlevel import set_xmodmap, parse_keysym, parse_modifier, get_minmax_keycodes, get_keycode_mappings         #@UnresolvedImport
from wimpiggy.log import Logger
log = Logger()

#debug = log.info
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
                log.info("%s", args)
            else:
                log.info("%s with stdin=%s", args, logstdin())
        else:
            log.info("%s with stdin=%s, failed with exit code %s", args, logstdin(), returncode)
        return returncode
    except Exception, e:
        log.info("error calling '%s': %s" % (str(args), e))
        return -1


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
        for setting in ["rules", "model", "layout"]:
            if setting in settings:
                args += ["-%s" % setting, settings.get(setting)]
        if len(args)==1:
            log.info("do_set_keymap could not find rules, model or layout in the xkbmap query string..")
        exec_keymap_command(args)
        #try to set the options:
        if "options" in settings:
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
        log.info("do_set_keymap using '%s' default layout", layout)
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
    debug("set_all_keycodes(%s..., %s.., %s)", str(xkbmap_x11_keycodes)[:60], str(xkbmap_keycodes)[:60], preserve_server_keycodes, modifiers)
    #get the list of keycodes (either from x11 keycodes or gtk keycodes):
    if False and xkbmap_x11_keycodes and len(xkbmap_x11_keycodes)>0:
        debug("using x11 keycodes: %s", xkbmap_x11_keycodes)
        keycodes = x11_keycodes_to_list(xkbmap_x11_keycodes)
    else:
        debug("using gtk keycodes: %s", xkbmap_keycodes)
        keycodes = gtk_keycodes_to_list(xkbmap_keycodes)
    debug("x11 keycodes=%s", keycodes)

    #now lookup the current keycodes (if we need to preserve them)
    preserve_keycode_entries = []
    if preserve_server_keycodes:
        import gtk.gdk
        x11_mappings = get_keycode_mappings(gtk.gdk.get_default_root_window())
        debug("get_keycode_mappings=%s", x11_mappings)
        preserve_keycode_entries = x11_keycodes_to_list(x11_mappings)
        debug("preserve x11 mappings=%s", preserve_server_keycodes)

    kcmin, kcmax = get_minmax_keycodes()
    trans, new_keycodes = translate_keycodes(kcmin, kcmax, keycodes, preserve_keycode_entries, modifiers)
    instructions = keymap_to_xmodmap(new_keycodes)
    unset = apply_xmodmap(instructions)
    debug("unset=%s", unset)
    return trans

def gtk_keycodes_to_list(gtk_mappings):
    """
        Takes gtk keycodes as obtained by get_gtk_keymap, in the form:
        #[(keyval, keyname, keycode, group, level), ..]
        And returns a list of entries in the form:
        [[keysym, keycode, index], ..]
    """
    #use the keycodes supplied by gtk:
    entries = []
    for _, name, keycode, group, level in gtk_mappings:
        if keycode<=0:
            continue            #ignore old 'add_if_missing' client side code
        if level in (2, 3):
            #please don't ask... I don't know what they're doing
            group = 1
            level -= 2
        index = group*4+level
        entries.append([name, keycode, index])
    return entries

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


def translate_keycodes(kcmin, kcmax, xkbmap_keycodes, preserve_keycode_entries=[], modifiers={}):
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
    debug("translate_keycodes(%s, %s, %s, %s, %s)", kcmin, kcmax, xkbmap_keycodes, preserve_keycode_entries, modifiers)
    #make it easier for us to lookup preserved keycodes:
    all_preserved_keycodes = set()          #the set of keycodes we want to preserve
    preserved_keycodes = {}                 #map a keycode we want to preserve to its entries
    preserved_keynames = {}                 #map a keysym to the keycodes we want to preserve
    for entry in preserve_keycode_entries:
        name, keycode, _ = entry
        entries = preserved_keycodes.setdefault(keycode, [])
        if entry not in entries:
            entries.append(entry)
        keycodes = preserved_keynames.setdefault(name, [])
        if keycode not in keycodes:
            keycodes.append(keycode)
        if keycode not in all_preserved_keycodes:
            all_preserved_keycodes.add(keycode)
    preserved_candidates = {}               #map a preserve keycode to the keycodes that have at least some of the same keysyms
    for keycode, entries in preserved_keycodes.items():
        keysyms = [name for name, _, _ in entries]
        keycodes = set([kc for name, kc, _ in xkbmap_keycodes if name in keysyms])
        if len(keycodes)>0:
            preserved_candidates[keycode] = keycodes
    debug("preserved_candidates=%s", preserved_candidates)
    debug("preserved_keynames=%s", preserved_keynames)

    #list of free keycodes we can use:
    #TODO: if we use a preserved keycode, the keycode is now free again... 
    free_keycodes = []
    input_keycodes = [keycode for (_, keycode, _) in xkbmap_keycodes]
    for i in range(kcmin, kcmax):
        if i not in input_keycodes and i not in all_preserved_keycodes:
            free_keycodes.append(i)

    #keep track of which keysym is bound to which modifier
    #(so we can avoid having more than one such keysym per keycode)
    keysym_to_modifier = {}
    for mod, keysyms in modifiers.items():
        for keysym in keysyms:
            existing_mod = keysym_to_modifier.get(keysym)
            if existing_mod and existing_mod!=mod:
                log.error("found a keysym mapped to more than one modifier: %s is mapped to both %s and %s !", keysym, mod, existing_mod)
            else:
                keysym_to_modifier[keysym] = mod

    keycode_to_modifier = {}        #once we assign a keycode, record the modifier (if any) here
    used = []                       #all the keycodes we have used
    keycode_trans = {}              #translation map from client keycode to our server keycode
    server_keycodes = []            #the new keycode definitions

    def do_assign(keycode, server_keycode, entries):
        """ may change the keycode if needed
            in which case we update the entries and populate 'keycode_trans'
        """
        if server_keycode in used:
            used_by = [entry for entry in server_keycodes if entry[1]==server_keycode]
            debug("assign: keycode %s already in use: %s", server_keycode, used_by)
            server_keycode = 0
        elif server_keycode>0 and (server_keycode<kcmin or server_keycode>kcmax):
            debug("assign: keycode %s out of range (%s to %s)", server_keycode, kcmin, kcmax)
            server_keycode = 0
        if server_keycode<=0:
            if len(free_keycodes)>0:
                server_keycode = free_keycodes[0]
                free_keycodes.remove(server_keycode)
                debug("set_keycodes key %s using free keycode=%s", entries, server_keycode)
            else:
                log.error("set_keycodes: no free keycodes!, cannot translate %s: %s", server_keycode, entries)
                server_keycode = 0
        if server_keycode>0 and server_keycode!=keycode:
            verbose("set_keycodes key %s (%s) mapped to keycode=%s", keycode, entries, server_keycode)
            for name, _, _ in entries:
                keycode_trans[(keycode, name)] = server_keycode
                #keycode_trans[keycode] = server_keycode
            used.append(server_keycode)
            #keycode should now be free
            if keycode not in free_keycodes:
                free_keycodes.append(keycode)
        if server_keycode>0:
            #ensure the keycode recorded is the one we will use:
            for entry in entries:
                entry[1] = server_keycode
            for x in entries:
                server_keycodes.append(x)
            for name, _, _ in entries:
                modifier = keysym_to_modifier.get(name)
                if modifier:
                    existing_modifier = keycode_to_modifier.get(server_keycode)
                    if existing_modifier and existing_modifier!=modifier:
                        log.error("error assigning server keycode %s: was already recorded as modifier %s but we now have %s!", server_keycode, existing_modifier, modifier)
                    else:
                        keycode_to_modifier[server_keycode] = modifier
        return server_keycode

    def assign(keycode, entries):
        if len(all_preserved_keycodes)==0:
            return [do_assign(keycode, keycode, entries)]    #nothing to preserve shortcut
        preserve_keycodes = set()
        for name, _, _ in entries:
            keycodes = preserved_keynames.get(name)
            if keycodes:
                for k in keycodes:
                    preserve_keycodes.add(k)
        if len(preserve_keycodes)==0:
            server_keycode = keycode
            candidate = preserved_candidates.get(server_keycode)
            debug("no preserve keycodes for %s, candidate(%s)=%s", entries, server_keycode, candidate)
            if candidate:
                server_keycode = 0
            return [do_assign(keycode, server_keycode, entries)]    #no matching keys to preserve were found
        nokeycode_entries = [(name, index) for [name, _, index] in entries]
        verbose("preserved keycodes for %s: %s", entries, preserve_keycodes)
        preserved_used = []
        for server_keycode in preserve_keycodes:
            if server_keycode in used:
                debug("preserved keycode %s already in use", server_keycode)
                continue
            #debug("%s in used: %s", sk, sk in used)
            preserve_entries = preserved_keycodes.get(server_keycode)
            verbose("testing preserved entries for keycode %s: %s to match %s", server_keycode, preserve_entries, entries)
            if preserve_entries==entries:
                assert server_keycode==keycode
                verbose("identical preserved match: %s", entries)
                preserved_used.append(do_assign(keycode, server_keycode, entries))
                continue
            #now try to ignore the keycode:
            nokeycode_preserve_entries = [(name, index) for [name, _, index] in preserve_entries]
            if nokeycode_preserve_entries==nokeycode_entries:
                assert server_keycode!=keycode
                verbose("new keycode %s for preserved match: %s", server_keycode, preserve_entries)
                preserved_used.append(do_assign(keycode, server_keycode, entries))
                continue
            #do we have a subset?
            if set(nokeycode_entries).issubset(set(nokeycode_preserve_entries)):
                verbose("new keycode %s for subset match: %s", server_keycode, preserve_entries)
                preserved_used.append(do_assign(keycode, server_keycode, preserve_entries))
                continue
            #maybe this is the only entry that matches this server keycode?
            candidates = preserved_candidates.get(server_keycode, [])
            if len(candidates)>1:
                debug("preserved_candidates(%s)=%s ", server_keycode, candidates)
            if candidates and len(candidates)==1 and list(candidates)[0]==keycode:
                verbose("new keycode %s for unique keysym match: %s", server_keycode, preserve_entries)
                preserved_used.append(do_assign(keycode, server_keycode, entries))
                continue
        if len(preserved_used)>0:
            return preserved_used
        preserved = [preserved_keycodes.get(kc) for kc in preserve_keycodes]
        debug("found preserve for %s but none of the keycodes %s are usable: %s, will assign a new keycode", entries, list(preserve_keycodes), preserved)
        return [do_assign(keycode, 0, entries)]

    #group by keycode:
    keycodes = {}
    for entry in xkbmap_keycodes:
        _, keycode, _ = entry
        keycodes.setdefault(keycode, []).append(list(entry))

    #now try to assign each keycode:
    for keycode, entries in keycodes.items():
        assign(keycode, entries)
    debug("server_keycodes=%s", server_keycodes)

    #find all keysyms:
    all_keysyms = set()
    for x in [entry[0] for entry in server_keycodes]:
        all_keysyms.add(x)
    debug("all_keysyms=%s", all_keysyms)

    #defined keysyms for modifiers if some are missing:
    for modifier, keysyms in modifiers.items():
        for keysym in keysyms:
            if keysym not in all_keysyms:
                debug("found missing keysym %s for modifier %s, will add it", keysym, modifier)
                new_key = [[keysym, 0, 0], [keysym, 0, 2]]
                new_keycode = assign(0, new_key)
                debug("assigned keycode %s for key '%s' of modifier '%s'", new_keycode, keysym, modifier)

    debug("translated keycodes=%s", keycode_trans)
    debug("%s free keycodes=%s", len(free_keycodes), free_keycodes)
    return keycode_trans, server_keycodes


def keymap_to_xmodmap(server_keycodes):
    """
        Given a dict with keycodes as keys and lists of keyboard entries as values,
        produce a list of xmodmap instructions to set the x11 keyboard to match it,
        in the form:
        ("keycode", keycode, [keysyms])
    """
    #group by keycode:
    trans_keycodes = {}
    for entry in server_keycodes:
        _, keycode, _ = entry
        trans_keycodes.setdefault(keycode, []).append(entry)

    missing_keysyms = []            #the keysyms lookups which failed
    instructions = []
    for server_keycode, entries in trans_keycodes.items():
        keysyms = [None, None, None, None, None, None, None, None]
        names = []
        for name, _keycode, index in entries:
            names.append(name)
            if index not in range(0, 8):
                log.warn("illegal index for %s: %s, %s", name, index)
                continue
            try:
                keysym = parse_keysym(name)
            except:
                keysym = None
            if keysym is None:
                missing_keysyms.append(name)
            else:
                if keysyms[index] is not None:
                    log.warn("we already have a keysym for %s at index %s: %s, entries=%s", _keycode, index, keysyms[index], entries)
                else:
                    keysyms[index] = keysym
        #X11 docs don't make sense, whatever...
        if keysyms[0] is not None and keysyms[2] is None:
            keysyms[2] = keysyms[0]
        if keysyms[1] is not None and keysyms[3] is None:
            keysyms[3] = keysyms[1]
        if len([x for x in keysyms if x is not None])>0:
            debug("%s: %s -> %s", server_keycode, names, keysyms)
            instructions.append(("keycode", server_keycode, keysyms))
        else:
            log.warn("no valid keysyms for keycode %s", _keycode)

    if missing_keysyms:
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
        Note: each modifier must use different keycodes.
    """
    instructions = []
    for modifier, keynames in modifiers.items():
        mod = parse_modifier(modifier)
        if mod>=0:
            instructions.append(("add", mod, keynames))
        else:
            log.error("set_modifiers_from_dict: unknown modifier %s", modifier)
    debug("set_modifiers_from_dict: %s", instructions)
    unset = apply_xmodmap(instructions)
    debug("unset=%s", unset)
    return  modifiers


def get_modifiers_from_meanings(xkbmap_mod_meanings):
    """
        xkbmap_mod_meanings maps a keyname to a modifier
        returns keynames_for_mod: {modifier : [keynames]}
    """
    #first generate a {modifier : [keynames]} dict:
    modifiers = {}
    for keyname, modifier in xkbmap_mod_meanings.items():
        keynames = modifiers.setdefault(modifier, [])
        keynames.append(keyname)
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
    all_keynames = []
    for entry in xkbmap_keycodes:
        _, keyname, _, _, _ = entry
        modifier = pref.get(keyname)
        if modifier:
            keynames = matches.setdefault(modifier, [])
            if keyname not in keynames:
                keynames.append(keyname)
            if keyname not in all_keynames:
                all_keynames.append(keyname)
    #add default missing ones if we can:
    debug("get_modifiers_from_keycodes(...) matches=%s", matches)
    defaults = {}
    for keyname, modifier in DEFAULT_MODIFIER_MEANINGS.items():
        if keyname in all_keynames:
            continue
        if modifier in matches:
            continue
        defaults.setdefault(modifier, []).append(keyname)
    debug("get_modifiers_from_keycodes(...) adding defaults: %s", defaults)
    matches.update(defaults)
    debug("get_modifiers_from_keycodes(...)=%s", matches)
    return matches
