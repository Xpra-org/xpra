# This file is part of Xpra.
# Copyright (C) 2013-2017 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing a list of entries of the form:
# username|password|uid|gid|displays|env_options|session_options

import os

from xpra.server.auth.file_auth_base import log, FileAuthenticatorBase, init as file_init
from xpra.os_util import strtobytes, hexstr, POSIX
from xpra.util import parse_simple_dict
from xpra.net.crypto import verify_digest


def init(opts):
    file_init(opts)


def getuid(v):
    if v:
        try:
            return int(v)
        except:
            log("uid '%s' is not an int", v)
    if POSIX:
        try:
            import pwd
            return pwd.getpwnam(v or "nobody").pw_uid
        except Exception as e:
            log.error("Error: cannot find uid of '%s': %s", v, e)
        return os.getuid()
    return -1

def getgid(v):
    if v:
        try:
            return int(v)
        except:
            log("gid '%s' is not an int", v)
    if POSIX:
        try:
            import grp          #@UnresolvedImport
            return grp.getgrnam(v or "nobody").gr_gid
        except Exception as e:
            log.error("Error: cannot find gid of '%s': %s", v, e)
        return os.getgid()
    return -1


def parse_auth_line(line):
    ldata = line.split(b"|")
    assert len(ldata)>=2, "not enough fields: %i" % (len(ldata))
    log("found %s fields", len(ldata))
    #parse fields:
    username = ldata[0]
    password = ldata[1]
    if len(ldata)>=5:
        uid = getuid(ldata[2])
        gid = getgid(ldata[3])
        displays = ldata[4].split(b",")
    else:
        uid, gid = -1, -1
        displays = []
    env_options = {}
    session_options = {}
    if len(ldata)>=6:
        env_options = parse_simple_dict(ldata[5], ";")
    if len(ldata)>=7:
        session_options = parse_simple_dict(ldata[6], ";")
    return username, password, uid, gid, displays, env_options, session_options


class Authenticator(FileAuthenticatorBase):
    def __init__(self, username, **kwargs):
        FileAuthenticatorBase.__init__(self, username, **kwargs)
        self.sessions = None

    def parse_filedata(self, data):
        if not data:
            return {}
        auth_data = {}
        i = 0
        for line in data.splitlines():
            i += 1
            line = line.strip()
            log("line %s: %s", i, line)
            if len(line)==0 or line.startswith(b"#"):
                continue
            try:
                v = parse_auth_line(line)
                if v:
                    username, password, uid, gid, displays, env_options, session_options = v
                    if username in auth_data:
                        log.error("Error: duplicate entry for username '%s' in '%s'", username, self.password_filename)
                    else:
                        auth_data[username] = password, uid, gid, displays, env_options, session_options
            except Exception as e:
                log("parsing error", exc_info=True)
                log.error("Error parsing password file '%s' at line %i:", self.password_filename, i)
                log.error(" '%s'", line)
                log.error(" %s", e)
                continue
        log("parsed auth data from file %s: %s", self.password_filename, auth_data)
        return auth_data

    def get_auth_info(self):
        self.load_password_file()
        if not self.password_filedata:
            return None
        return self.password_filedata.get(strtobytes(self.username))

    def get_password(self):
        entry = self.get_auth_info()
        log("get_password() found entry=%s", entry)
        if entry is None:
            return None
        return entry[0]

    def authenticate_hmac(self, challenge_response, client_salt=None):
        log("authenticate_hmac(%r, %r)", challenge_response, client_salt)
        self.sessions = None
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        #ensure this salt does not get re-used:
        salt = self.get_response_salt(client_salt)
        entry = self.get_auth_info()
        if entry is None:
            log.warn("Warning: authentication failed")
            log.warn(" no password for '%s' in '%s'", self.username, self.password_filename)
            return None
        log("authenticate: auth-info(%s)=%s", self.username, entry)
        fpassword, uid, gid, displays, env_options, session_options = entry
        log("multifile authenticate_hmac password='%r', hex(salt)=%s", fpassword, hexstr(salt))
        if not verify_digest(self.digest, fpassword, salt, challenge_response):
            log.warn("Warning: %s challenge for '%s' does not match", self.digest, self.username)
            return False
        self.sessions = uid, gid, displays, env_options, session_options
        return True

    def get_sessions(self):
        return self.sessions

    def __repr__(self):
        return "multi password file"
