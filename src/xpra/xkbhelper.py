# This file is part of Parti.
# Copyright (C) 2011, 2012 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import subprocess

from wimpiggy.error import trap
from wimpiggy.lowlevel import set_xmodmap, parse_keysym, parse_modifier, get_minmax_keycodes         #@UnresolvedImport
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
        if len(args)>0:
            exec_keymap_command(args)
        #try to set the options:
        if "options" in settings:
            exec_keymap_command(["setxkbmap", "-option", "", "-option", settings.get("options")])
    elif xkbmap_print:
        log.debug("do_set_keymap using xkbmap_print")
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
        log.info("do_set_keymap using 'us' default layout")
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
        #there may be a junk header, if so remove it:
        pos = xkbmap_print.find("xkb_keymap {")
        if pos>0:
            xkbmap_print = xkbmap_print[pos:]
        exec_keymap_command(["xkbcomp", "-", display], xkbmap_print)

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
    instructions = []
    for i in range(0, 8):
        instructions.append(("clear", i))
    apply_xmodmap(instructions)

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
