# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from typing import Any

from xpra.util.pid import write_pidfile, rm_pidfile
from xpra.util.env import osexpand
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("server")


class DaemonServer(StubServerMixin):

    def __init__(self):
        StubServerMixin.__init__(self)
        self.pidfile = ""
        self.pidinode: int = 0

    def init(self, opts) -> None:
        log("DaemonServer.init(%s)", opts)
        self.pidfile = osexpand(opts.pidfile)
        if self.pidfile:
            self.pidinode = write_pidfile(os.path.normpath(self.pidfile))

    def late_cleanup(self, stop=True) -> None:
        if self.pidfile:
            log("cleanup removing pidfile %s", self.pidfile)
            rm_pidfile(self.pidfile, self.pidinode)
            self.pidinode = 0

    def get_info(self, _proto) -> dict[str, Any]:
        if self.pidfile:
            return {
                "pidfile": {
                    "path": self.pidfile,
                    "inode": self.pidinode,
                }
            }
        return {}
