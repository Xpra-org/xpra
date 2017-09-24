# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import binascii

from xpra.platform.dotxpra import DotXpra
from xpra.util import xor
from xpra.net.crypto import get_salt, choose_digest, verify_digest
from xpra.os_util import strtobytes
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
        self.digest = None
        try:
            import pwd
            self.pw = pwd.getpwnam(username)
        except:
            self.pw = None
        #warn about unused options:
        unused = [(k,v) for k,v in kwargs.items() if k not in ("connection", "exec_cwd")]
        if unused:
            log.warn("Warning: unused keyword arguments for %s authentication:", self)
            log.warn(" %s", kwargs)

    def get_uid(self):
        if self.pw is None:
            raise Exception("username '%s' not found" % self.username)
        return self.pw.pw_uid

    def get_gid(self):
        if self.pw is None:
            raise Exception("username '%s' not found" % self.username)
        return self.pw.pw_gid

    def requires_challenge(self):
        return True

    def get_challenge(self, digests):
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return None
        self.salt = get_salt()
        self.digest = choose_digest(digests)
        #we need the raw password, so tell the client to use "xor":
        return self.salt, self.digest

    def get_password(self):
        return None

    def check(self, password):
        raise NotImplementedError()

    def authenticate(self, challenge_response, client_salt=None):
        #this will call check(password)
        return self.authenticate_check(challenge_response, client_salt)


    def get_response_salt(self, client_salt=None):
        server_salt = self.salt
        #clear it to make sure it does not get re-used:
        self.salt = None
        if client_salt is None:
            return server_salt
        salt = xor(server_salt, client_salt)
        log("combined salt(%s, %s)=%s", binascii.hexlify(server_salt), binascii.hexlify(client_salt), binascii.hexlify(salt))
        return salt

    def authenticate_check(self, challenge_response, client_salt=None):
        if self.salt is None:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return False
        salt = self.get_response_salt(client_salt)
        password = xor(challenge_response, salt)
        #warning: enabling logging here would log the actual system password!
        #log("authenticate(%s) password=%s", binascii.hexlify(challenge_response), password)
        #verify login:
        try :
            ret = self.check(password)
            log("authenticate_check(..)=%s", ret)
        except Exception as e:
            log.error("Error: %s authentication check failed:", self)
            log.error(" %s", e)
            return False
        return ret

    def authenticate_hmac(self, challenge_response, client_salt=None):
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        #ensure this salt does not get re-used:
        if client_salt is None:
            salt = self.salt
        else:
            salt = xor(self.salt, client_salt)
            log("xoring salt: xor(%s, %s)=%s", self.salt, client_salt, binascii.hexlify(strtobytes(salt)))
        self.salt = None
        password = self.get_password()
        if not password:
            log.warn("Warning: %s authentication failed", self)
            log.warn(" no password defined for '%s'", self.username)
            return False
        if not verify_digest(self.digest, password, salt, challenge_response):
            log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
            return False
        return True

    def get_sessions(self):
        uid = self.get_uid()
        gid = self.get_gid()
        log("%s.get_sessions() uid=%i, gid=%i", self, uid, gid)
        try:
            sockdir = DotXpra(socket_dir, socket_dirs, actual_username=self.username, uid=uid, gid=gid)
            results = sockdir.sockets(check_uid=uid)
            displays = []
            for state, display in results:
                if state==DotXpra.LIVE and display not in displays:
                    displays.append(display)
            log("sockdir=%s, results=%s, displays=%s", sockdir, results, displays)
        except Exception as e:
            log("get_sessions()", exc_info=True)
            log.error("Error: cannot get the list of sessions for '%s':", self.username)
            log.error(" %s", e)
            displays = []
        v = uid, gid, displays, {}, {}
        log("%s.get_sessions()=%s", self, v)
        return v
