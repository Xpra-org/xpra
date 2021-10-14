#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import signal
from subprocess import Popen, PIPE

from xpra.util import noerr, envbool
from xpra.os_util import (
    WIN32, OSX, POSIX,
    is_gnome, is_kde, which, bytestostr,
    use_gui_prompt, is_main_thread,
    )
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS, InitExit
from xpra.exit_codes import EXIT_UNSUPPORTED
from xpra.log import Logger

log = Logger("exec", "auth")

SKIP_UI = envbool("XPRA_SKIP_UI", False)
PINENTRY = envbool("XPRA_SSH_PINENTRY", POSIX and not OSX)

#pylint: disable=import-outside-toplevel


def get_pinentry_command(setting="yes"):
    log("get_pinentry_command(%s)", setting)
    if setting.lower() in FALSE_OPTIONS:
        return None
    def find_pinentry_bin():
        if is_gnome():
            return which("pinentry-gnome3")
        if is_kde():
            return which("pinentry-qt")
        return None
    if setting.lower() in TRUE_OPTIONS:
        return find_pinentry_bin() or which("pinentry")
    if setting=="" or setting.lower()=="auto":
        #figure out if we should use it:
        if WIN32 or OSX:
            #not enabled by default on those platforms
            return None
        return find_pinentry_bin()
    return setting

def popen_pinentry(pinentry_cmd):
    try:
        cmd = [pinentry_cmd]
        if log.is_debug_enabled():
            cmd.append("--debug")
        return Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except OSError as e:
        log("popen_pinentry(%s) failed", pinentry_cmd, exc_info=True)
        log.error("Error: failed to run '%s'", pinentry_cmd)
        log.error(" %s", e)
        return None

def run_pinentry(extra_args):
    messages = list(extra_args)
    def get_input():
        if not messages:
            return None
        return messages.pop(0)
    def process_output(message, line):
        if line.startswith(b"ERR "):
            log.error("Error: pinentry responded to '%s' with:", message)
            log.error(" %s", line.rstrip(b"\n\r").decode())
        else:
            log("pinentry sent %r", line)
    pinentry_cmd = get_pinentry_command() or "pinentry"
    proc = popen_pinentry(pinentry_cmd)
    if not proc:
        raise InitExit(EXIT_UNSUPPORTED, "cannot run pinentry")
    return do_run_pinentry(proc, get_input, process_output)

def do_run_pinentry(proc, get_input, process_output):
    message = "connection"
    while proc.poll() is None:
        try:
            line = proc.stdout.readline()
            while process_output(message, line):
                pass
            message = get_input()
            if message is None:
                break
            log("sending %r", message)
            r = proc.stdin.write(("%s\n" % message).encode())
            proc.stdin.flush()
            log("write returned: %s", r)
        except OSError:
            log("error running pinentry", exc_info=True)
            break
    if proc.poll() is None:
        proc.terminate()
    log("pinentry ended: %s" % proc.poll())

def pinentry_getpin(pinentry_proc, title, description, pin_cb, err_cb):
    from urllib.parse import quote
    messages = [
        "SETPROMPT %s" % quote(title),
        "SETDESC %s:" % quote(description),
        "GETPIN",
        ]
    def get_input():
        if not messages:
            return None
        return messages.pop(0)
    def process_output(message, output):
        if message=="GETPIN":
            if output.startswith(b"S "):
                log("getpin message: %s", bytestostr(output[2:]))
                #ie: 'S PASSWORD_FROM_CACHE'
                return True     #read more data
            if output.startswith(b"D "):
                pin_value = output[2:].rstrip(b"\n\r").decode()
                pin_cb(pin_value)
            else:
                err_cb()
    do_run_pinentry(pinentry_proc, get_input, process_output)
    return True

def run_pinentry_getpin(pinentry_cmd, title, description):
    proc = popen_pinentry(pinentry_cmd)
    if proc is None:
        return None
    values = []
    def rec(value=None):
        values.append(value)
    try:
        pinentry_getpin(proc, title, description, rec, rec)
    finally:
        noerr(proc.terminate)
    if not values:
        return None
    return values[0]

def run_pinentry_confirm(pinentry_cmd, title, prompt):
    proc = popen_pinentry(pinentry_cmd)
    if proc is None:
        return None
    messages = [
        #we can't use those as the response is multi-line:
        #"GETINFO flavor",
        #"GETINFO version",
        #"GETINFO pid",
        ]
    messages += [
        "SETPROMPT %s" % title,
        "SETDESC %s" % prompt,
        #"SETKEYINFO %c/%s"
        ]
    messages.append("CONFIRM")
    log("run_pinentry_confirm%s messages=%s", (pinentry_cmd, title, prompt), messages)
    def get_input():
        if not messages:
            return None
        return messages.pop(0)
    confirm_values = []
    def process_output(message, output):
        log("received %s for %s", output, message)
        if message=="CONFIRM":
            confirm_values.append(output.strip(b"\n\r"))
    do_run_pinentry(proc, get_input, process_output)
    if len(confirm_values)!=1:
        return None
    return bytestostr(confirm_values[0])    #ie: "OK"



def force_focus():
    from xpra.platform.gui import force_focus as _force_focus
    _force_focus()

def dialog_run(run_fn) -> int:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import GLib, Gtk
    log("dialog_run(%s) is_main_thread=%s, main_level=%i", run_fn, is_main_thread(), Gtk.main_level())
    if is_main_thread() or Gtk.main_level()==0:
        return run_fn()
    log("dialog_run(%s) main_depth=%s", run_fn, GLib.main_depth())
    #do a little dance if we're not running in the main thread:
    #block this thread and wait for the main thread to run the dialog
    from threading import Event
    e = Event()
    code = []
    def main_thread_run():
        log("main_thread_run() calling %s", run_fn)
        try:
            code.append(run_fn())
        finally:
            e.set()
    GLib.idle_add(main_thread_run)
    log("dialog_run(%s) waiting for main thread to run", run_fn)
    e.wait()
    log("dialog_run(%s) code=%s", run_fn, code)
    return code[0]

def do_run_dialog(dialog):
    try:
        force_focus()
        dialog.show()
        try:
            return dialog.run()
        finally:
            dialog.destroy()
    finally:
        dialog.destroy()

def dialog_pass(title="Password Input", prompt="enter password", icon="") -> str:
    log("dialog_pass%s PINENTRY=%s", (title, prompt, icon), PINENTRY)
    if PINENTRY:
        pinentry_cmd = get_pinentry_command()
        if pinentry_cmd:
            return run_pinentry_getpin(pinentry_cmd, title, prompt)
    def password_input_run():
        from xpra.client.gtk_base.pass_dialog import PasswordInputDialogWindow
        dialog = PasswordInputDialogWindow(title, prompt, icon)
        return do_run_dialog(dialog)
    return dialog_run(password_input_run)

def dialog_confirm(title, prompt, qinfo=(), icon="", buttons=(("OK", 1),)) -> int:
    def confirm_run():
        from xpra.client.gtk_base.confirm_dialog import ConfirmDialogWindow
        dialog = ConfirmDialogWindow(title, prompt, qinfo, icon, buttons)
        return do_run_dialog(dialog)
    return dialog_run(confirm_run)


def confirm(info=(), title="Confirm Key", prompt="Are you sure you want to continue connecting?") -> bool:
    log("confirm%s SKIP_UI=%s, PINENTRY=%s", (info, title, prompt), SKIP_UI, PINENTRY)
    if SKIP_UI:
        return False
    if PINENTRY:
        pinentry_cmd = get_pinentry_command()
        if pinentry_cmd:
            messages = list(info)+["", prompt]
            return run_pinentry_confirm(pinentry_cmd, title, "%0A".join(messages))=="OK"
    if use_gui_prompt():
        from xpra.platform.paths import get_icon_filename
        icon = get_icon_filename("authentication", "png") or ""
        NO_CODE = 199
        YES_CODE = 200
        code = dialog_confirm(title, prompt, info, icon, buttons=[("NO", NO_CODE), ("yes", YES_CODE)])
        log("dialog return code=%s", code)
        r = code==YES_CODE
        return r
    log("confirm%s will use stdin prompt", (info, title, prompt))
    prompt = "Are you sure you want to continue connecting (yes/NO)? "
    sys.stderr.write(os.linesep.join(info)+os.linesep+prompt)
    try:
        v = sys.stdin.readline().rstrip(os.linesep)
    except KeyboardInterrupt:
        sys.exit(128+signal.SIGINT)
    return v and v.lower() in ("y", "yes")

def input_pass(prompt) -> str:
    if SKIP_UI:
        return None
    if PINENTRY or use_gui_prompt():
        from xpra.platform.paths import get_icon_filename
        icon = get_icon_filename("authentication", "png") or ""
        log("input_pass(%s) using dialog", prompt)
        return dialog_pass("Password Input", prompt, icon)
    from getpass import getpass
    log("input_pass(%s) using getpass", prompt)
    try:
        return getpass(prompt)
    except KeyboardInterrupt:
        sys.exit(128+signal.SIGINT)
