# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

from xpra.platform.dotxpra import DotXpra
from xpra.util import xor
from xpra.os_util import get_hex_uuid
from xpra.log import Logger
log = Logger("auth")


socket_dir = None
socket_dirs = None
def init(opts):
    global socket_dir, socket_dirs
    socket_dir = opts.socket_dir
    socket_dirs = opts.socket_dirs


class SysAuthenticator(object):
    def __init__(self, username, **kwargs):
        self.username = username
        self.salt = None
        try:
            import pwd
            self.pw = pwd.getpwnam(username)
        except:
            self.pw = None
        if kwargs:
            log.warn("Warning: unused keyword arguments for %s authentication:", self)
            log.warn(" %s", kwargs)

    def get_uid(self):
        if self.pw is None:
            raise Exception("username %s not found" % self.username)
        return self.pw.pw_uid

    def get_gid(self):
        if self.pw is None:
            raise Exception("username %s not found" % self.username)
        return self.pw.pw_gid

    def requires_challenge(self):
        return True

    def get_challenge(self):
        if self.salt is not None:
            log.error("challenge already sent!")
            return None
        self.salt = get_hex_uuid()+get_hex_uuid()
        #we need the raw password, so tell the client to use "xor":
        return self.salt, "xor"

    def get_password(self):
        return None

    def check(self, password):
        raise NotImplementedError()

    def authenticate(self, challenge_response, client_salt):
        if self.salt is None:
            log.error("got a challenge response with no salt!")
            return False
        if client_salt is None:
            salt = self.salt
        else:
            salt = xor(self.salt, client_salt)
        self.salt = None
        password = xor(challenge_response, salt)
        #warning: enabling logging here would log the actual system password!
        #log("authenticate(%s) password=%s", challenge_response, password)
        #verify login:
        try :
            if not self.check(password):
                return False
        except Exception as e:
            log.error("authentication error: %s", e)
            return False
        return True

    def get_sessions(self):
        uid = self.get_uid()
        gid = self.get_gid()
        try:
            sockdir = DotXpra(socket_dir, socket_dirs, actual_username=self.username)
            results = sockdir.sockets(check_uid=uid)
            displays = [display for state, display in results if state==DotXpra.LIVE]
        except Exception as e:
            log.error("Error: cannot get socket directory for '%s':", self.username)
            log.error(" %s", e)
            displays = []
        return uid, gid, displays, {}, {}
