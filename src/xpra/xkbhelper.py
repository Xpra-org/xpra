# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import subprocess
import time

from wimpiggy.error import trap
from wimpiggy.lowlevel import set_xmodmap, parse_keycode, parse_keysym, get_keycodes, parse_modifier, get_minmax_keycodes         #@UnresolvedImport
from wimpiggy.log import Logger
log = Logger()


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

def exec_xmodmap(xmodmap_data):
    display = os.environ.get("DISPLAY")
    if not xmodmap_data or len(xmodmap_data)==0:
        return
    start = time.time()
    stdin = xmodmap_data
    if type(xmodmap_data)==list:
        stdin = "\n".join(xmodmap_data)
    if exec_keymap_command(["xmodmap", "-display", display, "-"], stdin)==0:
        return
    if time.time()-start>5:
        log.error("xmodmap timeout.. the keymap has not been applied")
        return
    log.error("re-running %s xmodmap lines one at a time to workaround the error..", len(xmodmap_data))
    for mod in stdin.splitlines():
        exec_keymap_command(["xmodmap", "-display", display, "-e", mod])

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
        if len(args)>0:
            exec_keymap_command(args)
        #try to set the options:
        if "options" in settings:
            exec_keymap_command(["setxkbmap", "-option", "", "-option", settings.get("options")])
    elif xkbmap_print:
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
        #just set the layout (use 'us' if we don't even have that information!)
        layout = xkbmap_layout or "us"
        set_layout = ["setxkbmap", "-layout", layout]
        if xkbmap_variant:
            set_layout += ["-variant", xkbmap_variant]
        if not exec_keymap_command(set_layout) and xkbmap_variant:
            log.info("error setting keymap with variant %s, retrying with just layout %s", xkbmap_variant, layout)
            set_layout = ["setxkbmap", "-layout", layout]
            exec_keymap_command(set_layout)

    display = os.environ.get("DISPLAY")
    if xkbmap_print:
        exec_keymap_command(["xkbcomp", "-", display], xkbmap_print)


def parse_xmodmap(xmodmap_data):
    if type(xmodmap_data)==str and xmodmap_data.find("\n"):
        xmodmap_data = xmodmap_data.splitlines()
    import pygtk
    pygtk.require("2.0")
    import gtk
    root = gtk.gdk.get_default_root_window()
    instructions = []
    for line in xmodmap_data:
        log("parsing: %s", line)
        if not line:
            continue
        try:
            parts = line.split()
            if parts[0]=="keycode" and len(parts)>2 and parts[2]=="=":
                keycode = parse_keycode(root, parts[1])
                if len(parts)==3:
                    #ie: 'keycode 123 ='
                    continue
                if keycode==0 and len(parts)==4:
                    #keycode=0 means "any", ie: 'keycode any = Shift_L'
                    instructions.append(("keycode", 0, parts[2:3]))
                    continue
                elif keycode>0:
                    #ie: keycode   9 = Escape NoSymbol Escape
                    keysyms = parts[3:]
                    instructions.append(("keycode", keycode, keysyms))
                    continue
            elif parts[0]=="clear" and len(parts)>=2:
                #ie: 'clear Lock' 
                modifier = parse_modifier(parts[1])
                if modifier<0:
                    log.error("unknown modifier: %s, ignoring '%s'", parts[1], line)
                else:
                    instructions.append(("clear", modifier))
                continue
            elif parts[0]=="add" and len(parts)>=3:
                #ie: 'add Control = Control_L Control_R'
                modifier = parse_modifier(parts[1])
                keysyms = parts[3:]
                if modifier<0:
                    log.error("unknown modifier: %s, ignoring '%s'", parts[1], line)
                elif len(keysyms)==0:
                    log.error("no keysyms! ignoring '%s'", line)
                else:
                    instructions.append(("add", modifier, keysyms))
                continue
            log.error("parse_xmodmap instruction not recognized: %s (%s parts: %s)", line, len(parts), parts)
        except Exception, e:
            log.error("cannot parse %s: %s", line, e)
    return instructions



def set_xmodmap_from_text(data):
    if not data:
        return
    instructions = parse_xmodmap(data)
    log.debug("instructions=%s", instructions)
    unset = apply_xmodmap(instructions)
    log.debug("unset=%s", unset)
    if len(unset)>0:
        #re-do everything... ouch!
        exec_xmodmap(data)



def set_all_keycodes(xkbmap_keycodes, xkbmap_initial_keycodes):
    """
        Both parameters should contain a list of:
        (keyval, keyname, keycode, group, level)
        The first one contains the desired keymap,
        the second one the initial X11 server keycodes.
        We try to preserve the initial keycodes
        Returns a translation map for keycodes.
    """
    # The preserve_keycodes is a dict containing {keysym:keycode}
    # for keys we want to preserve the keycode for.
    # By default, all keys which have a name and group=level=0
    preserve_keycodes = {}
    for (_, keyname, keycode, group, level) in xkbmap_initial_keycodes:
        if group==0 and level==0 and keyname:
            preserve_keycodes[keyname] = keycode
    # convert the keycode entries into a dict where the keycode is the key:
    # {keycode : (keyval, name, keycode, group, level)}
    # since the instructions are generated per keycode in set_keycodes()
    keycodes = {}
    log.debug("set_all_keycodes_preserve(%s..., %s..)", str(xkbmap_keycodes)[:120], str(preserve_keycodes)[:120])
    for entry in xkbmap_keycodes:
        _, _, keycode, _, _ = entry
        entries = keycodes.setdefault(keycode, [])
        entries.append(entry)
    return set_keycodes(keycodes, preserve_keycodes)

def set_keycodes(keycodes, preserve_keycodes={}):
    """
        The keycodes given may not match the range that the server supports,
        so we return a translation map for those keycodes that have been
        remapped.
        The preserve_keycodes is a dict containing {keysym:keycode}
        for keys we want to preserve the keycode for.
    """
    kcmin,kcmax = get_minmax_keycodes()
    free_keycodes = []
    for i in range(kcmin, kcmax):
        if i not in keycodes.keys() and i not in preserve_keycodes.values():
            free_keycodes.append(i)
    log.debug("set_keycodes(..) min=%s, max=%s, free_keycodes=%s", kcmin, kcmax, free_keycodes)

    used = []
    trans = {}
    instructions = []
    for keycode, entries in keycodes.items():
        server_keycode = keycode
        if preserve_keycodes:
            for entry in entries:
                (_, name, _, group, level) = entry
                if group==0 and level==0 and name in preserve_keycodes:
                    server_keycode = preserve_keycodes.get(name)
                    if server_keycode!=keycode:
                        log.debug("set_keycodes key %s(%s) mapped to keycode=%s", keycode, entries, server_keycode)
        if server_keycode==0 or server_keycode in used or server_keycode<kcmin or server_keycode>kcmax:
            if len(free_keycodes)>0:
                server_keycode = free_keycodes[0]
                free_keycodes = free_keycodes[1:]
                log.debug("set_keycodes key %s(%s) out of range or already in use, using free keycode=%s", keycode, entries, server_keycode)
            else:
                log.error("set_keycodes: no free keycodes!, cannot translate %s: %s", keycode, entries)
                continue
        if server_keycode!=keycode and keycode!=0:
            trans[keycode] = server_keycode
        used.append(server_keycode)
        keysyms = []
        #sort them by group then level
        def sort_key(entry):
            (_, _, _, group, level) = entry
            return group*10+level
        sentries = sorted(entries, key=sort_key)
        for (_, name, _keycode, _, _) in sentries:
            assert _keycode == keycode
            try:
                keysym = parse_keysym(name)
            except:
                keysym = None
            if keysym is None:
                log.error("cannot find keysym for %s", name)
            else:
                keysyms.append(keysym)
        if len(keysyms)>=2 and len(keysyms)<=6:
            keysyms = keysyms[:2]+keysyms
        if len(keysyms)>0:
            instructions.append(("keycode", server_keycode, keysyms))
    log.debug("instructions=%s", instructions)
    unset = apply_xmodmap(instructions)
    log.debug("unset=%s", unset)
    log.debug("translated keycodes=%s", trans)
    log.debug("%s free keycodes=%s", len(free_keycodes), free_keycodes)
    return  trans


def clear_modifiers(modifiers):
    set_xmodmap_from_text([("clear %s" % x) for x in modifiers])

def set_modifiers_from_meanings(xkbmap_mod_meanings):
    """
        xkbmap_mod_meanings maps a keyname to a modifier
        returns keynames_for_mod: {modifier : [keynames]}
    """
    #first generate a {modifier : [keynames]} dict:
    modifiers = {}
    for keyname, modifier in xkbmap_mod_meanings.items():
        keynames = modifiers.setdefault(modifier, [])
        keynames.append(keyname)
    log.debug("set_modifiers(%s) modifier dict=%s", xkbmap_mod_meanings, modifiers)
    return set_modifiers_from_dict(modifiers)

def set_modifiers_from_dict(modifiers):
    """
        modifiers is a dict: {modifier : [keynames]}
    """
    instructions = []
    for modifier, keynames in modifiers.items():
        mod = parse_modifier(modifier)
        if mod>=0:
            instructions.append(("add", mod, keynames))
        else:
            log.error("set_modifiers_from_dict: unknown modifier %s", modifier)
    log.debug("set_modifiers_from_dict: %s", instructions)
    unset = apply_xmodmap(instructions)
    log.debug("unset=%s", unset)
    return  modifiers

def set_modifiers_from_keycodes(xkbmap_keycodes):
    """
        Some platforms can't tell us about modifier mappings
        So we try to find matches from the defaults below:
    """
    from xpra.keys import DEFAULT_MODIFIER_MEANINGS
    pref = DEFAULT_MODIFIER_MEANINGS
    #{keycode : (keyval, name, keycode, group, level)}
    matches = {}
    log.info("set_modifiers_from_keycodes(%s...)", str(xkbmap_keycodes)[:160])
    for entry in xkbmap_keycodes:
        _, keyname, _, _, _ = entry
        modifier = pref.get(keyname)
        if modifier:
            keynames = matches.setdefault(modifier, [])
            if keyname not in keynames:
                keynames.append(keyname)
    log.debug("set_modifiers_from_keycodes(..) found matches: %s", matches)
    return set_modifiers_from_dict(matches)


def set_modifiers_from_text(xkbmap_mod_add):
    """
        This is the old, backwards compatibility method..
        We are given some modifiers instructions in plain text,
        and if missing we use the ones from XMODMAP_MOD_ADD.
        We parse those and then must ensure all the key names
        actually exist before trying to change the keymap.
        We must also ensure that keycodes are only assigned to
        a single modifier. 
        This is also used to ensure that the keynames_for_mod
        dict we return is valid.
    """
    import gtk.gdk
    root = gtk.gdk.get_default_root_window()
    from xpra.keys import XMODMAP_MOD_ADD, ALL_X11_MODIFIERS
    instructions = parse_xmodmap(xkbmap_mod_add or XMODMAP_MOD_ADD)
    log.debug("instructions=%s", instructions)
    oked = []
    keycodes_used = {}
    modifiers = {}
    for instr in instructions:
        if not instr or instr[0]!="add":
            log.error("invalid instruction in modifier text: %s", instr)
            continue
        modifier_int = instr[1]
        modifier = -1
        for m,v in ALL_X11_MODIFIERS.items():
            if v==modifier_int:
                modifier = m
                break
        if modifier<0:
            log.error("unknown modifier int: %s", modifier)
            continue
        keysyms_strs = instr[2]
        keysyms = []
        for keysym_str in keysyms_strs:
            keycodes = get_keycodes(root, keysym_str)
            if len(keycodes)==0:
                log.debug("keysym '%s' does not have a keycode, ignoring: %s", keysym_str, keysym_str)
                continue
            #found some keycodes, so we can use this keysym
            #after first verifying they aren't used yet:
            keycodes_free = True
            for keycode in keycodes:
                if keycode in keycodes_used:
                    log.debug("%s as keycode %s is already used by %s, ignoring: %s", keysym_str, keycode, keycodes_used.get(keycode), instr)
                    keycodes_free = False
                    break
            if keycodes_free:
                for keycode in keycodes:
                    keycodes_used[keycode] = modifier
                keysyms.append(keysym_str)
        if len(keysyms)>0:
            modifiers[modifier] = keysyms
            oked.append(("add", modifier_int, keysyms))
    log.debug("set_modifiers_from_text: %s", oked)
    unset = apply_xmodmap(oked)
    log.debug("set_modifiers_from_text failed on: %s", unset)
    log.debug("set_modifiers_from_text(..)=%s", modifiers)
    return  modifiers
