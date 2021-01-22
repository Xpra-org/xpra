# This file is part of Xpra.
# Copyright (C) 2019-2020 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os

from xpra.os_util import load_binary_file
from xpra.log import Logger

log = Logger("auth")

class Handler:

    def __init__(self, client, **kwargs):
        self.client = client
        self.password_file = kwargs.get("filename", None)
        if not self.password_file:
            if client.password_file:
                self.password_file = client.password_file[0]
                client.password_file = client.password_file[1:]

    def __repr__(self):
        return "file"

    def get_digest(self) -> str:
        return None

    def handle(self, packet) -> bool:
        log("handle(..) password_file=%s", self.password_file)
        if not self.password_file:
            return False
        filename = os.path.expanduser(self.password_file)
        data = load_binary_file(filename)
        log("loaded password data from %s: %s", filename, bool(data))
        if not data:
            return False
        self.client.send_challenge_reply(packet, data)
        return True
