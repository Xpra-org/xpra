# This file is part of Xpra.
# Copyright (C) 2017-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen
from gi.repository import GLib

from xpra.util import envint, typedict
from xpra.os_util import OSX
from xpra.child_reaper import getChildReaper
from xpra.server.auth.sys_auth_base import SysAuthenticator, log
from xpra.platform.features import EXECUTABLE_EXTENSION

TIMEOUT = envint("XPRA_EXEC_AUTH_TIMEOUT", 600)


class Authenticator(SysAuthenticator):

    def __init__(self, **kwargs):
        log("exec.Authenticator(%s)", kwargs)
        self.command = kwargs.pop("command", "")
        self.timeout = kwargs.pop("timeout", TIMEOUT)
        self.timer = None
        self.proc = None
        self.timeout_event = False
        if not self.command:
            if os.name == "posix":
                auth_dialog = "/usr/libexec/xpra/auth_dialog"
            else:
                from xpra.platform.paths import get_app_dir  #pylint: disable=import-outside-toplevel
                auth_dialog = os.path.join(get_app_dir(), "auth_dialog")
            if EXECUTABLE_EXTENSION:
                #ie: add ".exe" on MS Windows
                auth_dialog += ".%s" % EXECUTABLE_EXTENSION
            log("auth_dialog=%s", auth_dialog)
            if os.path.exists(auth_dialog):
                self.command = auth_dialog
        assert self.command, "exec authentication module is not configured correctly: no command specified"
        connection = kwargs.get("connection")
        log("exec connection info: %s", connection)
        assert connection, "connection object is missing"
        self.connection_str = str(connection)
        super().__init__(**kwargs)

    def requires_challenge(self) -> bool:
        return bool(self.http_request)

    def authenticate(self, caps : typedict) -> bool:
        info = "Connection request from %s" % self.connection_str
        cmd = [self.command, info, str(self.timeout)]
        with Popen(cmd) as proc:
            self.proc = proc
            log("authenticate(..) Popen(%s)=%s", cmd, proc)
            #if required, make sure we kill the command when it times out:
            if self.timeout>0:
                self.timer = GLib.timeout_add(self.timeout*1000, self.command_timedout)
                if not OSX:
                    #python on macos may set a 0 returncode when we use poll()
                    #so we cannot use the ChildReaper on macos,
                    #and we can't cancel the timer
                    getChildReaper().add_process(proc, "exec auth", cmd, True, True, self.command_ended)
        v = proc.returncode
        log("authenticate(..) returncode(%s)=%s", cmd, v)
        if self.timeout_event:
            return False
        return v==0

    def command_ended(self, *args):
        t = self.timer
        log("exec auth.command_ended%s timer=%s", args, t)
        if t:
            self.timer = None
            GLib.source_remove(t)

    def command_timedout(self):
        proc = self.proc
        log("exec auth.command_timedout() proc=%s", proc)
        self.timeout_event = True
        self.timer = None
        if proc:
            try:
                proc.terminate()
            except Exception:
                log("error trying to terminate exec auth process %s", proc, exc_info=True)

    def __repr__(self):
        return "exec"
