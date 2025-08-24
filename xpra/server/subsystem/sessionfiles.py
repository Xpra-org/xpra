# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.scripts.session import clean_session_files, rm_session_dir
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("server")


class SessionFilesServer(StubServerMixin):
    PREFIX = "session-files"

    def __init__(self):
        StubServerMixin.__init__(self)
        self.session_files: list[str] = []

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
