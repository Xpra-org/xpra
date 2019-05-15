# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.util import std
from xpra.os_util import bytestostr


class Handler(object):

    def __init__(self, client, **_kwargs):
        self.client = client

    def __repr__(self):
        return "prompt"

    def get_digest(self):
        return None

    def handle(self, packet):
        prompt = "password"
        digest = bytestostr(packet[3])
        if digest.startswith("gss:") or digest.startswith("kerberos:"):
            prompt = "%s token" % (digest.split(":", 1)[0])
        if len(packet)>=6:
            prompt = std(bytestostr(packet[5]))
        return self.client.do_process_challenge_prompt(packet, prompt)
