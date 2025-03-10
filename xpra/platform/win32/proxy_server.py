# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from time import sleep
from typing import Any
from collections.abc import Sequence

from xpra.server.proxy.server import ProxyServer as _ProxyServer, get_proxy_env
from xpra.platform.paths import get_app_dir
from xpra.common import SocketState
from xpra.util.env import envbool
from xpra.util.io import pollwait, which
from xpra.log import Logger

log = Logger("proxy")

PAEXEC = envbool("XPRA_PAEXEC", True)
SYSTEM_SESSION = envbool("XPRA_SYSTEM_SESSION", True)
TOKEN = envbool("XPRA_SYSTEM_TOKEN", False)


def exec_command(username: str, password: str, args: Sequence[str], exe: str, cwd: str, env: dict[str, str]):
    log("exec_command%s", (username, args, exe, cwd, env))
    # pylint: disable=import-outside-toplevel
    from xpra.platform.win32.lsa_logon_lib import logon_msv1, logon_msv1_s4u
    if TOKEN:
        logon_info = logon_msv1_s4u(username)
    else:
        logon_info = logon_msv1(username, password)
    log("logon(..)=%s", logon_info)
    from xpra.platform.win32.create_process_lib import (
        Popen,
        CREATIONINFO, CREATION_TYPE_LOGON,
        STARTF_USESHOWWINDOW,
        LOGON_WITH_PROFILE, CREATE_NEW_PROCESS_GROUP, STARTUPINFO,
    )
    creation_info = CREATIONINFO()
    creation_info.lpApplicationName = "Xpra"
    creation_info.lpUsername = username
    creation_info.lpPassword = password
    creation_info.lpDomain = os.environ.get("USERDOMAIN", "WORKGROUP")
    #creation_info.dwCreationType = CREATION_TYPE_TOKEN
    creation_info.dwCreationType = CREATION_TYPE_LOGON
    creation_info.dwLogonFlags = LOGON_WITH_PROFILE
    creation_info.dwCreationFlags = CREATE_NEW_PROCESS_GROUP
    creation_info.hToken = logon_info.Token
    log("creation_info=%s", creation_info)
    startupinfo = STARTUPINFO()
    startupinfo.dwFlags = STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0  # aka win32.con.SW_HIDE
    startupinfo.lpDesktop = "WinSta0\\Default"
    startupinfo.lpTitle = "Xpra-Shadow"

    from subprocess import PIPE
    proc = Popen(args, executable=exe,
                 stdout=PIPE, stderr=PIPE,
                 cwd=cwd, env=env,
                 startupinfo=startupinfo, creationinfo=creation_info)
    log("Popen(%s)=%s", args, proc)
    return proc


class ProxyServer(_ProxyServer):

    def start_new_session(self, username: str, password: str, uid: int, gid: int,
                          sess_options: dict, displays=()) -> tuple[Any, str, str]:
        log("start_new_session%s", (username, "..", uid, gid, sess_options, displays))
        return self.start_win32_shadow(username, password, sess_options)

    def start_win32_shadow(self, username: str, password: str, sess_options: dict) -> tuple[Any, str, str]:
        log("start_win32_shadow%s", (username, "..", sess_options))
        app_dir = get_app_dir()
        shadow_command = app_dir + "\\Xpra-Shadow.exe"
        paexec = app_dir + "\\paexec.exe"
        named_pipe = username.replace(" ", "_")

        # pylint: disable=import-outside-toplevel
        from xpra.platform.win32.wtsapi import find_session
        session_info = find_session(username)
        if not session_info:
            # first, Logon:
            with log.trap_error(f"Error: failed to logon as {username!r}"):
                from xpra.platform.win32.desktoplogon_lib import logon
                r = logon(username, password)
            #if r:
            #    raise RuntimeError(f"desktop logon has failed and returned {r}")
        # hwinstaold = set_window_station("winsta0")
        wrap = []

        # use paexec to access the GUI session:
        if PAEXEC and os.path.exists(paexec) and os.path.isfile(paexec):
            # find the session-id to shadow:
            if not session_info:
                session_info = find_session(username)
            if session_info:
                log(f"found session {session_info} for {username!r}")
                wrap = [
                    "paexec.exe",
                    "-i", str(session_info["SessionID"]),
                ]
            elif username.lower() == "administrator" and SYSTEM_SESSION:
                log("using system session")
                wrap = [
                    "paexec.exe", "-x",
                ]
            else:
                log.warn("Warning: session not found for username '%s'", username)
        else:
            log(f"{PAEXEC=}, {paexec=!r}")
            log.warn("Warning: starting without paexec, expect a black screen")

        cmd = wrap + [
            shadow_command,
            f"--bind={named_pipe}",
            # "--tray=no",
        ]
        # unless explicitly stated otherwise, exit with client:
        if sess_options.get("exit-with-client", None) is not False:
            cmd.append("--exit-with-client=yes")
        from xpra.log import debug_enabled_categories
        if debug_enabled_categories:
            cmd += ["-d", ",".join(tuple(debug_enabled_categories))]
        env = get_proxy_env()
        env["XPRA_REDIRECT_OUTPUT"] = "1"
        exe = which(cmd[0])
        # env["XPRA_LOG_FILENAME"] = "Shadow-Instance.log"
        if username.lower() == "administrator" and SYSTEM_SESSION:
            # don't login
            from subprocess import Popen
            proc = Popen(cmd, executable=exe)
        else:
            proc = exec_command(username, password, cmd, exe, app_dir, env)

        from xpra.platform.win32.dotxpra import DotXpra
        dotxpra = DotXpra()
        for t in range(10):
            r = pollwait(proc, 1)
            if r is not None:
                log("pollwait=%s", r)
                try:
                    log("stdout=%s", proc.stdout.read())
                    log("stderr=%s", proc.stderr.read())
                except (OSError, AttributeError):
                    log("failed to read stdout / stderr of subprocess", exc_info=True)
                if r != 0:
                    raise RuntimeError(f"shadow subprocess failed with exit code {r}")
                raise RuntimeError("shadow subprocess has already terminated")
            if t >= 4:
                state = dotxpra.get_display_state(named_pipe)
                log("get_display_state(%s)=%s", named_pipe, state)
                if state == SocketState.LIVE:
                    # TODO: test the named pipe
                    sleep(2)
                    break
        self.child_reaper.add_process(proc, f"server-{username}", "xpra shadow", True, True)
        return proc, f"named-pipe://{named_pipe}", named_pipe
