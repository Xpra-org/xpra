# This file is part of Xpra.
# Copyright (C) 2019-2022 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class Handler:

    def __init__(self, client, **_kwargs):
        self.client = client

    def __repr__(self):
        return "uri"

    def get_digest(self) -> str:
        return None

    def handle(self, challenge, digest, prompt) -> bool:
        return self.client.password
