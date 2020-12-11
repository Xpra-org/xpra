# This file is part of Xpra.
# Copyright (C) 2013-2018 Antoine Martin <antoine@xpra.org>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

import os
from collections import deque

from xpra.platform.dotxpra import DotXpra
from xpra.util import envint, obsc
from xpra.net.digest import get_salt, choose_digest, verify_digest, gendigest
from xpra.os_util import hexstr, POSIX
from xpra.log import Logger
log = Logger("auth")

USED_SALT_CACHE_SIZE = envint("XPRA_USED_SALT_CACHE_SIZE", 1024*1024)
DEFAULT_UID = os.environ.get("XPRA_AUTHENTICATION_DEFAULT_UID", "nobody")
DEFAULT_GID = os.environ.get("XPRA_AUTHENTICATION_DEFAULT_GID", "nobody")


socket_dir = None
socket_dirs = None
def init(opts):
    global socket_dir, socket_dirs
    socket_dir = opts.socket_dir
    socket_dirs = opts.socket_dirs


def parse_uid(v):
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log("uid '%s' is not an int", v)
    if POSIX:
        try:
            import pwd
            return pwd.getpwnam(v or DEFAULT_UID).pw_uid
        except Exception as e:
            log("parse_uid(%s)", v, exc_info=True)
            log.error("Error: cannot find uid of '%s': %s", v, e)
        return os.getuid()
    return -1

def parse_gid(v):
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            log("gid '%s' is not an int", v)
    if POSIX:
        try:
            import grp          #@UnresolvedImport
            return grp.getgrnam(v or DEFAULT_GID).gr_gid
        except Exception as e:
            log("parse_gid(%s)", v, exc_info=True)
            log.error("Error: cannot find gid of '%s': %s", v, e)
        return os.getgid()
    return -1


class SysAuthenticatorBase(object):
    USED_SALT = deque(maxlen=USED_SALT_CACHE_SIZE)

    def __init__(self, username, **kwargs):
        self.username = username
        self.salt = None
        self.digest = None
        self.salt_digest = None
        self.prompt = kwargs.pop("prompt", "password")
        self.challenge_sent = False
        self.passed = False
        self.password_used = None
        #warn about unused options:
        unused = dict((k,v) for k,v in kwargs.items() if k not in ("connection", "exec_cwd"))
        if unused:
            log.warn("Warning: unused keyword arguments for %s authentication:", self)
            log.warn(" %s", unused)

    def get_uid(self):
        raise NotImplementedError()

    def get_gid(self):
        raise NotImplementedError()

    def requires_challenge(self):
        return True

    def get_challenge(self, digests):
        if self.salt is not None:
            log.error("Error: authentication challenge already sent!")
            return None
        self.salt = get_salt()
        self.digest = choose_digest(digests)
        self.challenge_sent = True
        return self.salt, self.digest

    def get_passwords(self):
        p = self.get_password()     #pylint: disable=assignment-from-none
        if p is not None:
            return (p,)
        return ()

    def get_password(self):
        return None

    def check(self, _password):
        return False

    def authenticate(self, challenge_response=None, client_salt=None):
        #this will call check(password)
        assert self.challenge_sent and not self.passed
        return self.authenticate_check(challenge_response, client_salt)

    def choose_salt_digest(self, digest_modes):
        self.salt_digest = choose_digest(digest_modes)
        return self.salt_digest

    def get_response_salt(self, client_salt=None):
        server_salt = self.salt
        #make sure it does not get re-used:
        self.salt = None
        if client_salt is None:
            return server_salt
        salt = gendigest(self.salt_digest, client_salt, server_salt)
        if salt in SysAuthenticator.USED_SALT:
            raise Exception("danger: an attempt was made to re-use the same computed salt")
        log("combined salt(%s, %s)=%s", hexstr(server_salt), hexstr(client_salt), hexstr(salt))
        SysAuthenticator.USED_SALT.append(salt)
        return salt

    def authenticate_check(self, challenge_response, client_salt=None):
        if self.salt is None:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return False
        salt = self.get_response_salt(client_salt)
        password = gendigest("xor", challenge_response, salt)
        log("authenticate_check(%s, %s) response salt=%s",
            obsc(repr(challenge_response)), repr(client_salt), repr(salt))
        #warning: enabling logging here would log the actual system password!
        #log.info("authenticate(%s, %s) password=%s (%s)",
        #    hexstr(challenge_response), hexstr(client_salt), password, hexstr(password))
        #verify login:
        try :
            ret = self.check(password)
            log("authenticate_check(..)=%s", ret)
        except Exception as e:
            log("check(..)", exc_info=True)
            log.error("Error: %s authentication check failed:", self)
            log.error(" %s", e)
            return False
        return ret

    def authenticate_hmac(self, challenge_response, client_salt=None):
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        salt = self.get_response_salt(client_salt)
        passwords = self.get_passwords()
        if not passwords:
            log.warn("Warning: %s authentication failed", self)
            log.warn(" no password defined for '%s'", self.username)
            return False
        log("found %i passwords using %s", len(passwords), type(self))
        for x in passwords:
            if verify_digest(self.digest, x, salt, challenge_response):
                self.password_used = x
                return True
        log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
        if len(passwords)>1:
            log.warn(" checked %i passwords", len(passwords))
        return False

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


class SysAuthenticator(SysAuthenticatorBase):

    def __init__(self, username, **kwargs):
        SysAuthenticatorBase.__init__(self, username)
        self.pw = None
        if POSIX:
            try:
                import pwd
                self.pw = pwd.getpwnam(username)
            except Exception:
                log("cannot load password database entry for '%s'", username, exc_info=True)

    def get_uid(self):
        if self.pw is None:
            raise Exception("username '%s' not found" % self.username)
        return self.pw.pw_uid

    def get_gid(self):
        if self.pw is None:
            raise Exception("username '%s' not found" % self.username)
        return self.pw.pw_gid
