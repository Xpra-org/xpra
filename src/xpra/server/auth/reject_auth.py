# This file is part of Xpra.
# Copyright (C) 2014-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.


from xpra.net.crypto import get_salt, choose_digest

def init(opts):
    pass


class Authenticator(object):
    def __init__(self, username, **kwargs):
        pass

    def requires_challenge(self):
        return True

    def get_challenge(self, digests):
        return get_salt(), choose_digest(digests)

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

    def __repr__(self):
        return "reject"
