# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.scripts.session import clean_session_files, rm_session_dir
from xpra.server.subsystem.stub import StubSubsystem
from xpra.log import Logger

log = Logger("server")


class SessionFilesServer(StubSubsystem):
    PREFIX = "session-files"

    def __init__(self, server=None):
        StubSubsystem.__init__(self, server)
        # canonical list of per-session files / glob patterns to clean up
        # at shutdown. Other subsystems append to this via `get_subsystem`.
        self.session_files: list[str] = [
            "cmdline", "server.env", "config", "server.log*",
            # notifications may use a TMP dir:
            "tmp/*", "tmp",
        ]

    def late_cleanup(self, stop=True) -> None:
        if stop:
            log("clean_session_files(%s)", self.session_files)
            clean_session_files(*self.session_files)
            if stop:
                rm_session_dir()

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            SessionFilesServer.PREFIX: self.session_files,
        }
