#!/usr/bin/env python
# This file is part of Xpra.
# Copyright (C) 2016-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen, PIPE

from xpra.util import nonl
from xpra.os_util import POSIX, bytestostr, close_fds
from xpra.scripts.server import _get_int, _get_str, _save_int, _save_str
from xpra.scripts.config import FALSE_OPTIONS
from xpra.log import Logger

log = Logger("dbus")


def start_dbus(dbus_launch):
    if not dbus_launch or dbus_launch.lower() in FALSE_OPTIONS:
        log("start_dbus(%s) disabled", dbus_launch)
        return 0, {}
    bus_address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    log("dbus_launch=%s, current DBUS_SESSION_BUS_ADDRESS=%s", dbus_launch, bus_address)
    if bus_address:
        log("start_dbus(%s) disabled, found an existing DBUS_SESSION_BUS_ADDRESS=%s", dbus_launch, bus_address)
        return 0, {}
    assert POSIX
    try:
        def preexec():
            os.setsid()
            close_fds()
        env = dict((k,v) for k,v in os.environ.items() if k in (
            "PATH",
            "SSH_CLIENT", "SSH_CONNECTION",
            "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR",
            "SHELL", "LANG", "USER", "LOGNAME", "HOME",
            "DISPLAY", "XAUTHORITY", "CKCON_X11_DISPLAY",
            ))
        import shlex
        cmd = shlex.split(dbus_launch)
        log("start_dbus(%s) env=%s", dbus_launch, env)
        proc = Popen(cmd, stdin=PIPE, stdout=PIPE, shell=False, env=env, preexec_fn=preexec)
        out = proc.communicate()[0]
        assert proc.poll()==0, "exit code is %s" % proc.poll()
        #parse and add to global env:
        dbus_env = {}
        log("out(%s)=%s", cmd, nonl(out))
        for l in bytestostr(out).splitlines():
            if l.startswith("export "):
                continue
            sep = "="
            if l.startswith("setenv "):
                l = l[len("setenv "):]
                sep = " "
            if l.startswith("set "):
                l = l[len("set "):]
            parts = l.split(sep, 1)
            if len(parts)!=2:
                continue
            k,v = parts
            if v.startswith("'") and v.endswith("';"):
                v = v[1:-2]
            elif v.endswith(";"):
                v = v[:-1]
            dbus_env[k] = v
        dbus_pid = int(dbus_env.get("DBUS_SESSION_BUS_PID", 0))
        log("dbus_pid=%i, dbus-env=%s", dbus_pid, dbus_env)
        return dbus_pid, dbus_env
    except Exception as e:
        log("start_dbus(%s)", dbus_launch, exc_info=True)
        log.error("dbus-launch failed to start using command '%s':\n" % dbus_launch)
        log.error(" %s\n" % e)
        return 0, {}


def save_dbus_pid(pid):
    _save_int(b"_XPRA_DBUS_PID", pid)

def get_saved_dbus_pid():
    return _get_int(b"_XPRA_DBUS_PID")

def get_saved_dbus_env():
    env = {}
    for n,load in (
            ("ADDRESS",     _get_str),
            ("PID",         _get_int),
            ("WINDOW_ID",   _get_int)):
        k = "DBUS_SESSION_BUS_%s" % n
        try:
            v = load(k)
            if v:
                env[k] = bytestostr(v)
        except Exception as e:
            log.error("failed to load dbus environment variable '%s':\n" % k)
            log.error(" %s\n" % e)
    return env

def save_dbus_env(env):
    #DBUS_SESSION_BUS_ADDRESS=unix:abstract=/tmp/dbus-B8CDeWmam9,guid=b77f682bd8b57a5cc02f870556cbe9e9
    #DBUS_SESSION_BUS_PID=11406
    #DBUS_SESSION_BUS_WINDOWID=50331649
    def u(s):
        try:
            return s.decode("latin1")
        except Exception:
            return str(s)
    for n,conv,save in (
            ("ADDRESS",     u,    _save_str),
            ("PID",         int,    _save_int),
            ("WINDOW_ID",   int,    _save_int)):
        k = "DBUS_SESSION_BUS_%s" % n
        v = env.get(k)
        if v is None:
            continue
        try:
            tv = conv(v)
            save(k, tv)
        except Exception as e:
            log("save_dbus_env(%s)", env, exc_info=True)
            log.error("failed to save dbus environment variable '%s' with value '%s':\n" % (k, v))
            log.error(" %s\n" % e)
