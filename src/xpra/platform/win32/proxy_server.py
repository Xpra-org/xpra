# This file is part of Xpra.
# Copyright (C) 2013-2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.server.proxy.proxy_server import ProxyServer as _ProxyServer
from xpra.platform.paths import get_app_dir
from xpra.log import Logger

log = Logger("proxy")
authlog = Logger("proxy", "auth")


def exec_command(username, command, env):
    log("exec_command%s", (username, command, env))
    from xpra.platform.win32.lsa_logon_lib import logon_msv1_s4u
    logon_info = logon_msv1_s4u(username)
    log("logon_msv1_s4u(%s)=%s", username, logon_info)
    from xpra.platform.win32.create_process_lib import (
        Popen,
        CREATIONINFO, CREATION_TYPE_TOKEN,
        LOGON_WITH_PROFILE, CREATE_NEW_PROCESS_GROUP, STARTUPINFO,
        )
    creation_info = CREATIONINFO()
    creation_info.dwCreationType = CREATION_TYPE_TOKEN
    creation_info.dwLogonFlags = LOGON_WITH_PROFILE
    creation_info.dwCreationFlags = CREATE_NEW_PROCESS_GROUP
    creation_info.hToken = logon_info.Token
    log("creation_info=%s", creation_info)
    startupinfo = STARTUPINFO()
    startupinfo.lpDesktop = "WinSta0\\Default"
    startupinfo.lpTitle = "Xpra-Shadow"
    cwd = get_app_dir()
    from subprocess import PIPE
    log("env=%s", env)
    proc = Popen(command, stdout=PIPE, stderr=PIPE, cwd=cwd, env=env,
                 startupinfo=startupinfo, creationinfo=creation_info)
    log("Popen(%s)=%s", command, proc)
    log("poll()=%s", proc.poll())
    try:
        log("stdout=%s", proc.stdout.read())
        log("stderr=%s", proc.stderr.read())
    except (OSError, IOError, AttributeError):
        pass
    if proc.poll() is not None:
        return None
    return proc

class ProxyServer(_ProxyServer):

    def start_new_session(self, username, uid, gid, new_session_dict=None, displays=()):
        log("start_new_session%s", (username, uid, gid, new_session_dict, displays))
        return self.start_win32_shadow(username, new_session_dict)

    def start_win32_shadow(self, username, new_session_dict):
        log("start_win32_shadow%s", (username, new_session_dict))
        #hwinstaold = set_window_station("winsta0")
        #whoami = os.path.join(get_app_dir(), "whoami.exe")
        #exec_command([whoami])
        port = 10000
        xpra_command = os.path.join(get_app_dir(), "xpra.exe")
        command = [
            xpra_command,
            "shadow",
            "--bind-tcp=0.0.0.0:%i" % port,
            ]
        from xpra.log import debug_enabled_categories
        if debug_enabled_categories:
            command += ["-d", ",".join(tuple(debug_enabled_categories))]
        env = self.get_proxy_env()
        proc = exec_command(username, command, env)
        if not proc:
            return None, None
        self.child_reaper.add_process(proc, "server-%s" % username, "xpra shadow", True, True)
        #exec_command(["C:\\Windows\notepad.exe"])
        return "tcp/localhost:%i" % port, proc
