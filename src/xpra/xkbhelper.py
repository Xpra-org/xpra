# This file is part of Parti.
# Copyright (C) 2010-2011 Antoine Martin <antoine@devloop.org.uk>
# Parti is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import re
import subprocess
import time

from wimpiggy.lowlevel import set_xmodmap                 #@UnresolvedImport
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
    if exec_keymap_command(["xmodmap", "-display", display, "-"], "\n".join(xmodmap_data))==0:
        return
    if time.time()-start>5:
        log.error("xmodmap timeout.. the keymap has not been applied")
        return
    log.error("re-running %s xmodmap lines one at a time to workaround the error..", len(xmodmap_data))
    if type(xmodmap_data)!=str:
        for mod in xmodmap_data:
            exec_keymap_command(["xmodmap", "-display", display, "-e", mod])

def c_xmodmap(data):
    import gtk.gdk
    unset = set_xmodmap(gtk.gdk.get_default_root_window(), data)
    exec_xmodmap(unset)





def do_set_keymap(xkbmap_layout, xkbmap_variant,
                  xkbmap_print, xkbmap_query):
    """ xkbmap_layout is the generic layout name (used on non posix platforms)
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


def do_set_xmodmap(xkbmap_mod_clear, xmodmap_data, xkbmap_mod_add):
    """ xkbmap_mod_clear is list of modifier clear instructions
            (ie: "clear shift") 
        xmodmap_data is the output of "xmodmap -pke" on the client
        xkbmap_mod_add is a list of modifier add instructions
            (ie: "add shift = Shift_L Shift_R")
    """
    # note: our code does not handle add/clear so we use exec_xmodmap for those
    if not xmodmap_data and not xkbmap_mod_add and not xkbmap_mod_clear:
        #clients before v0.0.7.32 didn't send defaults, so duplicate them here for now:
        from xpra.keys import XMODMAP_MOD_DEFAULTS, XMODMAP_MOD_ADD, XMODMAP_MOD_CLEAR
        exec_xmodmap(XMODMAP_MOD_CLEAR)
        c_xmodmap(XMODMAP_MOD_DEFAULTS)
        exec_xmodmap(XMODMAP_MOD_ADD)
    else:
        exec_xmodmap(xkbmap_mod_clear)
        c_xmodmap(xmodmap_data)
        exec_xmodmap(xkbmap_mod_add)
