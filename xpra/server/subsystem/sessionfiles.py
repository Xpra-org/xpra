# This file is part of Xpra.
# Copyright (C) 2010 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from typing import Any

from xpra.scripts.session import rm_session_dir, clean_session_files
from xpra.server.subsystem.stub import StubServerMixin
from xpra.log import Logger

log = Logger("server")


class SessionFilesServer(StubServerMixin):

    def __init__(self):
        self.session_files: list[str] = []

    def late_cleanup(self, stop=True) -> None:
        if stop:
            self.clean_session_files()
            rm_session_dir()

    def clean_session_files(self) -> None:
        log("clean_session_files() %s", *self.session_files)
        clean_session_files(*self.session_files)

    def get_info(self, _proto) -> dict[str, Any]:
        return {
            "session-files": self.session_files,
        }
