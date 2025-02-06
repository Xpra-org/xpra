# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.challenge.handler import AuthenticationHandler


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        self.password = kwargs.get("password", "")

    def __repr__(self):
        return "uri"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge: bytes, digest: str, prompt: str) -> str:  # pylint: disable=unused-argument
        return self.password
