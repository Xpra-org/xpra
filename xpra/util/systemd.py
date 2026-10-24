#!/usr/bin/env python3
# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import sys
import shlex
import signal
from subprocess import Popen, PIPE, TimeoutExpired

from xpra.common import noop, noerr
from xpra.os_util import POSIX, OSX, getuid
from xpra.util.env import envbool
from xpra.util.io import load_binary_file
from xpra.util.parsing import parse_bool_or
from xpra.util.system import stop_proc

SYSTEMD_RUN: bool = envbool("XPRA_SYSTEMD_RUN", True)


def is_systemd_pid1() -> bool:
    if not POSIX:
        return False
    d = load_binary_file("/proc/1/cmdline")
    return d.find(b"/systemd") >= 0


def systemd_run_command(mode: str, systemd_run_args="", user: bool = True) -> list[str]:
    cmd = ["systemd-run", "--description", "xpra-%s" % mode, "--scope"]
    if user:
        cmd.append("--user")
    log_systemd_wrap = envbool("XPRA_LOG_SYSTEMD_WRAP", True)
    if not log_systemd_wrap:
        cmd.append("--quiet")
    if systemd_run_args:
        cmd += shlex.split(systemd_run_args)
    return cmd


def systemd_run_wrap(mode: str, args, systemd_run_args="", user: bool = True, **kwargs) -> int:
    cmd = systemd_run_command(mode, systemd_run_args, user)
    cmd += args
    cmd.append("--systemd-run=no")
    errwrite = getattr(sys.stderr, "write", noop)
    if envbool("XPRA_LOG_SYSTEMD_WRAP", True):
        noerr(errwrite, f"using systemd-run to wrap {mode!r} xpra server subcommand\n")
    if envbool("XPRA_LOG_SYSTEMD_WRAP_COMMAND", False):
        noerr(errwrite, "%s\n" % " ".join(["'%s'" % x for x in cmd]))
    try:
        with Popen(cmd, **kwargs) as p:
            return p.wait()
    except KeyboardInterrupt:
        return 128 + signal.SIGINT


def use_systemd_run(s) -> bool:
    if not SYSTEMD_RUN or not POSIX or OSX:
        return False  # pragma: no cover
    systemd_run = parse_bool_or("systemd-run", s)
    if systemd_run in (True, False):
        return systemd_run
    # detect if we should use it:
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CLIENT"):  # pragma: no cover
        # would fail
        return False
    if not is_systemd_pid1():
        return False  # pragma: no cover
    # test it:
    cmd = ["systemd-run", "--quiet"]
    if getuid() != 0:
        cmd += ["--user"]
    cmd += ["--scope", "--", "true"]
    proc = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=False)
    try:
        proc.communicate(timeout=2)
        r = proc.returncode
    except TimeoutExpired:  # pragma: no cover
        r = None
    if r is None:
        stop_proc(proc, "systemd-run")
        if proc.poll() is None:
            try:
                proc.communicate(timeout=1)
            except TimeoutExpired:  # pragma: no cover
                r = None
    return r == 0
