# This file is part of Xpra.
# Copyright (C) 2013, 2014 Antoine Martin <antoine@devloop.org.uk>
# Xpra is released under the terms of the GNU GPL v2, or, at your option, any
# later version. See the file COPYING for details.

#authentication from a file containing a list of entries of the form:
# username|password|uid|gid|displays|env_options|session_options

import os
import binascii
import hmac, hashlib

from xpra.server.auth.file_auth import Authenticator as FileAuthenticator, init as file_init, load_password_file
from xpra.os_util import strtobytes
from xpra.util import xor
from xpra.log import Logger
log = Logger("auth")


socket_dir = None
socket_dirs = None
password_file = None
def init(opts):
    file_init(opts)
    global password_file, socket_dir, socket_dirs
    password_file = opts.password_file
    socket_dir = opts.socket_dir
    socket_dirs = opts.socket_dirs


def parseOptions(s):
    #ie: s="compression_level=1;lz4=0", ...
    #alternatives: ast, json/simplejson, ...
    if not s:
        return {}
    options = {}
    for e in s.split(";"):
        parts = e.split("=", 1)
        if len(parts)!=2:
            continue
        options[parts[0]] = parts[1]
    return options

auth_data = None
def load_auth_file():
    global password_file, socket_dir, socket_dirs
    file_data = load_password_file()
    auth_data = {}
    if file_data:
        i = 0
        for line in file_data.splitlines():
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
                        log.error("Error: duplicate entry for username '%s' in %s", username, password_file)
                    else:
                        auth_data[username] = password, uid, gid, displays, env_options, session_options
            except Exception as e:
                log("parsing error", exc_info=True)
                log.error("Error parsing password file line %i:", i)
                log.error(" '%s'", line)
                log.error(" %s", e)
                continue
    log("parsed auth data from file %s: %s", password_file, auth_data)
    return auth_data

def parse_auth_line(line):
    ldata = line.split(b"|")
    log("found %s fields", len(ldata))
    assert len(ldata)>=4, "not enough fields"
    #parse fields:
    username = ldata[0]
    password = ldata[1]
    def getsysid(s, get_default_value):
        if s:
            try:
                return int(s)
            except:
                pass
        return get_default_value()
    uid = getsysid(ldata[2], os.getuid)
    gid = getsysid(ldata[3], os.getgid)
    displays = ldata[4].split(b",")
    env_options = {}
    session_options = {}
    if len(ldata)>=6:
        env_options = parseOptions(ldata[5])
    if len(ldata)>=7:
        session_options = parseOptions(ldata[6])
    return username, password, uid, gid, displays, env_options, session_options


class Authenticator(FileAuthenticator):
    def __init__(self, username):
        FileAuthenticator.__init__(self, username)
        self.sessions = None

    def get_auth_info(self):
        return load_auth_file().get(strtobytes(self.username))

    def get_password(self):
        entry = self.get_auth_info()
        if entry is None:
            return None
        return entry[0]

    def authenticate(self, challenge_response, client_salt):
        self.sessions = None
        if not self.salt:
            log.error("Error: illegal challenge response received - salt cleared or unset")
            return None
        #ensure this salt does not get re-used:
        if client_salt is None:
            salt = self.salt
        else:
            salt = xor(self.salt, client_salt)
        self.salt = None
        entry = self.get_auth_info()
        log("authenticate(%s) auth-info=%s", self.username, entry)
        if entry is None:
            log.error("Error: authentication failed")
            log.error(" no password for '%s' in %s", self.username, password_file)
            return None
        fpassword, uid, gid, displays, env_options, session_options = entry
        verify = hmac.HMAC(strtobytes(fpassword), strtobytes(salt), digestmod=hashlib.md5).hexdigest()
        log("authenticate(%s) password=%s, hex(salt)=%s, hash=%s", challenge_response, fpassword, binascii.hexlify(strtobytes(salt)), verify)
        if hasattr(hmac, "compare_digest"):
            eq = hmac.compare_digest(verify, challenge_response)
        else:
            eq = verify==challenge_response
        if not eq:
            log("expected '%s' but got '%s'", verify, challenge_response)
            log.error("Error: hmac password challenge for '%s' does not match", self.username)
            return False
        self.sessions = uid, gid, displays, env_options, session_options
        return True

    def get_sessions(self):
        return self.sessions

    def __repr__(self):
        return "multi password file"
