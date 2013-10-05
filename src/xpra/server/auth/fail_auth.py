# This file is part of Xpra.
# Copyright (C) 2013 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.os_util import get_hex_uuid

def init(opts):
    pass

class Authenticator(object):
    def __init__(self, username):
        pass

    def get_challenge(self):
        return get_hex_uuid(), "hmac"

    def get_uid(self):
        return -1

    def get_gid(self):
        return -1

    def get_password(self):
        return None

    def authenticate(self, challenge_response, client_salt):
        return False

    def get_sessions(self):
        return None
