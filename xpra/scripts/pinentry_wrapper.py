#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2021 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from subprocess import Popen, PIPE

from xpra.util import noerr
from xpra.os_util import WIN32, OSX, is_gnome, is_kde, which, bytestostr
from xpra.scripts.config import FALSE_OPTIONS, TRUE_OPTIONS, InitExit
from xpra.exit_codes import EXIT_UNSUPPORTED
from xpra.log import Logger

log = Logger("exec")


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
            process_output(message, line)
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
    messages = [
        "SETPROMPT %s" % title,
        "SETDESC %s:" % description,
        "GETPIN",
        ]
    def get_input():
        if not messages:
            return None
        return messages.pop(0)
    def process_output(message, output):
        if message=="GETPIN":
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

def run_pinentry_confirm(pinentry_cmd, title, prompt, notok=None):
    proc = popen_pinentry(pinentry_cmd)
    if proc is None:
        return None
    messages = []
    if notok:
        messages.append("SETNOTOK %s" % notok)
    messages += [
        "SETPROMPT %s" % title,
        "SETDESC %s" % prompt,
        ]
    messages.append("CONFIRM")
    log("run_pinentry_confirm%s messages=%s", (pinentry_cmd, title, prompt, notok), messages)
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
