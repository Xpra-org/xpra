# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
import time
from time import monotonic
from subprocess import Popen
from typing import Any

from xpra.util.env import envint, envbool
from xpra.util.system import stop_proc
from xpra.net.constants import SocketState
from xpra.scripts.args import get_start_server_args
from xpra.log import Logger, get_debug_args

WAIT_SERVER_TIMEOUT: int = envint("WAIT_SERVER_TIMEOUT", 90)


def proxy_start_win32_shadow(script_file, args, opts, dotxpra, display_name) -> tuple[Any, str, str]:
    log = Logger("server")
    from xpra.platform.paths import get_app_dir
    app_dir = get_app_dir()
    cwd = app_dir
    env = os.environ.copy()
    exe = script_file
    cmd = []
    if envbool("XPRA_PAEXEC", True):
        # use paexec to access the GUI session:
        paexec = os.path.join(app_dir, "paexec.exe")
        if os.path.exists(paexec) and os.path.isfile(paexec):
            from xpra.platform.win32.wtsapi import find_session
            from xpra.platform.info import get_username
            username = get_username()
            if session_info := find_session(username):
                cmd = [
                    "paexec.exe",
                    "-i", str(session_info["SessionID"]), "-s",
                ]
                exe = paexec
                # don't show a cmd window:
                script_file = script_file.replace("Xpra_cmd.exe", "Xpra.exe")
            else:
                log("session not found for user '%s', not using paexec", username)
    cmd += [script_file, "shadow"] + args
    cmd += get_start_server_args(opts)
    debug_args = os.environ.get("XPRA_SHADOW_DEBUG")
    if debug_args is None:
        debug_args = ",".join(get_debug_args())
    if debug_args:
        cmd.append(f"--debug={debug_args}")
    log(f"proxy shadow start command: {cmd}")
    proc = Popen(cmd, executable=exe, env=env, cwd=cwd)
    start = monotonic()
    elapsed = 0.0
    while elapsed < WAIT_SERVER_TIMEOUT:
        state = dotxpra.get_display_state(display_name)
        if state == SocketState.LIVE:
            log("found live server '%s'", display_name)
            # give it a bit of time:
            # FIXME: poll until the server is ready instead
            time.sleep(1)
            return proc, f"named-pipe://{display_name}", display_name
        log(f"get_display_state({display_name})={state} (waiting)")
        if proc.poll() not in (None, 0):
            raise RuntimeError(f"shadow subprocess command returned {proc.returncode}")
        time.sleep(0.10)
        elapsed = monotonic() - start
    stop_proc(proc, "shadow server")
    raise RuntimeError(f"timeout: failed to identify the new shadow server {display_name!r}")
