# This file is part of Xpra.
# Copyright (C) 2019-2024 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.client.auth.handler import AuthenticationHandler


class Handler(AuthenticationHandler):

    def __repr__(self):
        return "prompt"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge: bytes, digest: str, prompt: str = "password"):  # pylint: disable=unused-argument
        digest_type = digest.split(":", 1)[0]
        if not prompt and digest_type in ("gss", "kerberos"):
            prompt = f"{digest_type} token"
        return self.client.do_process_challenge_prompt(prompt)
