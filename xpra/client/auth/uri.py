# This file is part of Xpra.
# Copyright (C) 2019-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.client.auth.handler import AuthenticationHandler


class Handler(AuthenticationHandler):

    def __repr__(self):
        return "uri"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge: bytes, digest: str, prompt: str) -> str:  # pylint: disable=unused-argument
        return self.client.password
