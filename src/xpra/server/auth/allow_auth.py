# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import get_hex_uuid
from xpra.server.auth.sys_auth_base import SysAuthenticator

def init(opts):
    pass

class Authenticator(SysAuthenticator):

    def get_challenge(self):
        return get_hex_uuid(), "hmac"

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return True
