# This file is part of Xpra.
# Copyright (C) 2019 Antoine Martin <antoine@xpra.org>
# Copyright (C) 2022 Nathalie Casati <nat@yuka.ch>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


class Handler:

    def __init__(self, client, **_kwargs):
        self.client = client

    def __repr__(self):
        return "keycloak"

    def get_digest(self) -> str:
        return "keycloak"

    def handle(self, packet) -> bool:
        if not self.client.password:
            return False
        self.client.send_challenge_reply(packet, self.client.password)
        return True
