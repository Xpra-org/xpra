# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from collections.abc import Callable

from xpra.challenge.handler import AuthenticationHandler


PROMPT_FN_KEY = "challenge_prompt_function"


def noprompt(_prompt: str) -> str:
    return ""


class Handler(AuthenticationHandler):

    def __init__(self, **kwargs):
        self.challenge_prompt_fn: Callable[[str], str] = kwargs.get(PROMPT_FN_KEY, noprompt)

    def __repr__(self):
        return "prompt"

    def get_digest(self) -> str:
        return ""

    def handle(self, challenge: bytes, digest: str, prompt: str = "password"):  # pylint: disable=unused-argument
        digest_type = digest.split(":", 1)[0]
        if not prompt and digest_type in ("gss", "kerberos"):
            prompt = f"{digest_type} token"
        return self.challenge_prompt_fn(prompt)
