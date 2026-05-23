# This file is part of Xpra.
# Copyright (C) 2026 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.os_util import POSIX, getuid, get_shell_for_uid, get_username_for_uid, get_home_for_uid
from xpra.scripts.main import configure_env
from xpra.util.env import osexpand
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")


class ProcessServer(StubSubsystem):
    PREFIX = "process"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        self.uid = 0
        self.gid = 0
        self.protected_env: dict[str, str] = {}
        self.env = ()
        self.chdir = ""
        self.applied = False

    def init(self, opts) -> None:
        self.uid = int(opts.uid)
        self.gid = int(opts.gid)
        self.protected_env = dict(getattr(self.server, "protected_env", {}))
        self.env = tuple(opts.env)
        self.chdir = str(opts.chdir or "")

    def setup(self) -> None:
        if self.applied:
            return
        self.applied = True
        root = POSIX and getuid() == 0
        if root and (self.uid != 0 or self.gid != 0):
            username = get_username_for_uid(self.uid)
            home = get_home_for_uid(self.uid)
            log("root: switching to uid=%i, gid=%i", self.uid, self.gid)
            from xpra.util.daemon import setuidgid
            setuidgid(self.uid, self.gid)
            os.environ.update({
                "HOME": home,
                "USER": username,
                "LOGNAME": username,
            })
            shell = get_shell_for_uid(self.uid)
            if shell:
                os.environ["SHELL"] = shell
            # now we've changed uid, it is safe to honour all the env updates:
            configure_env(self.env)
            os.environ.update(self.protected_env)
            if not self.chdir:
                self.chdir = home
        else:
            configure_env(self.env)
        if self.chdir:
            log(f"chdir({self.chdir})")
            os.chdir(osexpand(self.chdir))

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            ProcessServer.PREFIX: {
                "uid": self.uid,
                "gid": self.gid,
                "root": POSIX and getuid() == 0,
                "chdir": self.chdir,
                "applied": self.applied,
            },
        }
