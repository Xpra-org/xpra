# This file is part of Xpra.
# Copyright (C) 2019-2023 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import load_binary_file
from xpra.log import Logger

log = Logger("auth")


class Handler:

    def __init__(self, client, **kwargs):
        self.client = client
        self.password_file : str = kwargs.get("filename", "")
        if not self.password_file and client.password_file:
            self.password_file = client.password_file[0]
            client.password_file = client.password_file[1:]

    def __repr__(self):
        return "file"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge, digest:str, prompt:str) -> bytes:  # pylint: disable=unused-argument
        log("handle(..) password_file=%s", self.password_file)
        if not self.password_file:
            return b""
        filename = os.path.expanduser(self.password_file)
        data = load_binary_file(filename)
        log("loaded password data from %s: %s", filename, bool(data))
        return data
