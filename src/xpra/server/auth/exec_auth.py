# This file is part of Xpra.
# Copyright (C) 2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from subprocess import Popen

from xpra.os_util import POSIX
from xpra.util import envint
from xpra.child_reaper import getChildReaper
from xpra.server.auth.sys_auth_base import SysAuthenticator, init, log
from xpra.gtk_common.gobject_compat import import_glib

glib = import_glib()

#will be called when we init the module
assert init

TIMEOUT = envint("XPRA_EXEC_AUTH_TIMEOUT", 600)


class Authenticator(SysAuthenticator):

    def __init__(self, username, **kwargs):
        log("exec.Authenticator(%s, %s)", username, kwargs)
        if not POSIX:
            log.warn("Warning: exec authentication is not supported on %s", os.name)
            return
        self.command = kwargs.pop("command", "")
        self.timeout = kwargs.pop("timeout", TIMEOUT)
        self.timer = None
        self.proc = None
        self.timeout_event = False
        if not self.command:
            #try to find the default auth_dialog executable:
            from xpra.platform.paths import get_libexec_dir
            libexec = get_libexec_dir()
            xpralibexec = os.path.join(libexec, "xpra")
            if os.path.exists(xpralibexec):
                libexec = xpralibexec
            auth_dialog = os.path.join(libexec, "auth_dialog")
            if os.path.exists(auth_dialog):
                self.command = auth_dialog
        assert self.command, "exec authentication module is not configured correctly: no command specified"
        connection = kwargs.get("connection")
        log("exec connection info: %s", connection)
        assert connection, "connection object is missing"
        self.connection_str = str(connection)
        SysAuthenticator.__init__(self, username, **kwargs)

    def requires_challenge(self):
        return False

    def authenticate(self, _challenge_response=None, _client_salt=None):
        info = "Connection request from %s" % self.connection_str
        cmd = [self.command, info, str(self.timeout)]
        self.proc = Popen(cmd, close_fds=True, shell=False)
        log("authenticate(..) Popen(%s)=%s", cmd, self.proc)
        #if required, make sure we kill the command when it times out:
        if self.timeout>0:
            self.timer = glib.timeout_add(self.timeout*1000, self.command_timedout)
            getChildReaper().add_process(self.proc, "exec auth", cmd, True, True, self.command_ended)
        v = self.proc.wait()
        log("authenticate(..) returncode(%s)=%s", cmd, v)
        if self.timeout and self.timeout_event:
            return False
        return v==0

    def command_ended(self, *args):
        t = self.timer
        log("exec auth.command_ended%s timer=%s", args, t)
        if t:
            self.timer = None
            glib.source_remove(t)

    def command_timedout(self):
        log("exec auth.command_timedout()")
        self.timeout_event = True
        self.timer = None

    def __repr__(self):
        return "exec"
