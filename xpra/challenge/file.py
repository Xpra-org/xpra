# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.challenge.handler import AuthenticationHandler
from xpra.util.io import load_binary_file
from xpra.log import Logger

log = Logger("auth")


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        if "filename" in kwargs:
            self.password_file: str = kwargs.get("filename", "")
            return
        if "password-files" in kwargs:
            files = kwargs.get("password-files", [])
            if files:
                self.password_file = files.pop(0)
                return
        self.password_file = ""

    def __repr__(self):
        return "file"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge: bytes, digest: str, prompt: str) -> bytes:  # pylint: disable=unused-argument
        log("handle(..) password_file=%s", self.password_file)
        if not self.password_file:
            return b""
        filename = os.path.expanduser(self.password_file)
        data = load_binary_file(filename)
        log("loaded password data from %s: %s", filename, bool(data))
        return data
